import json

import kopf
from kubernetes import client
from kubernetes.client.exceptions import ApiException

from src.config import Config
from src.dataset_service import (
    DatasetService,
    DatasetNotFoundError,
    DatasetServiceError,
)

SUCCESS_PHASE = "Succeeded"
FAILURE_PHASE = "Failed"
SCHEDULED_PHASE = "Scheduled"
PENDING_PHASE = "Pending"


class Controller:
    def __init__(
        self,
        batch_v1: client.BatchV1Api,
        custom_api: client.CustomObjectsApi,
        dataset_service: DatasetService,
        config: Config,
    ):
        self._batch_v1 = batch_v1
        self._custom_api = custom_api
        self._dataset_service = dataset_service
        self._config = config

    def reconcile(self, name: str, namespace: str, body: dict, logger):
        """
        Idempotent reconciliation for a TaskRequest.

        - If the TaskRequest is already in a terminal phase (Succeeded/Failed),
          it is a no-op.
        - If it is Scheduled (Job exists), its status is synced from the Job.
        - Otherwise (Pending or no status yet), the full reconciliation runs:
          fetch beta(d) per dataset, compute beta*(t), create the Job.
        """
        phase = (body.get("status") or {}).get("phase")

        if phase in (SUCCESS_PHASE, FAILURE_PHASE):
            logger.info(
                f"TaskRequest {name!r} is in terminal phase {phase!r}, skipping"
            )
            return

        if phase == SCHEDULED_PHASE:
            logger.info(
                f"TaskRequest {name!r} is already Scheduled, syncing Job status"
            )
            self._sync_from_job(name, namespace, logger)
            return

        # Phase is None or Pending, run full reconciliation.
        self._full_reconcile(name, namespace, body, logger)

    def sync_job_status(
        self, task_request_name: str, namespace: str, job_status, logger
    ):
        """Propagate a Job status change to the realted TaskRequest."""
        conditions = self._extract_conditions(job_status)
        self._apply_conditions(task_request_name, namespace, conditions, logger)

    def _full_reconcile(self, name: str, namespace: str, body: dict, logger):
        """
        Full reconciliation pipeline for a new or Pending TaskRequest:
            1. Set phase to Pending.
            3. Compute beta*(t) = LUB(beta(t), beta(d1), ...) delegated to DatasetService.
            4. Create the Job with beta* and dataset annotations.
            5. Set phase to Scheduled.
        """
        self._set_status(
            namespace=namespace,
            name=name,
            phase=PENDING_PHASE,
            message="",
            job_name="",
            logger=logger,
        )

        spec = body.get("spec") or {}
        requirements: dict = spec.get("requirements") or {}
        datasets: list = spec.get("datasets") or []

        try:
            beta_star = self._dataset_service.compute_effective_beta(
                beta_t=requirements, datasets=datasets
            )
            logger.info(f"TaskRequest {name!r}: beta*(t) = {beta_star}")
        except DatasetNotFoundError as e:
            logger.error(f"TaskRequest {name!r}: {e}")
            self._set_status(
                namespace=namespace,
                name=name,
                phase=FAILURE_PHASE,
                message=str(e),
                job_name="",
                logger=logger,
            )
            return
        except DatasetServiceError as e:
            logger.warning(
                f"TaskRequest {name!r} transient dataset service error: {e}"
            )
            raise kopf.TemporaryError(str(e), delay=10)
        
        owner_uid = body["metadata"]["uid"]
        job_body = self._build_job(name, namespace, beta_star, datasets, owner_uid)

        try:
            self._batch_v1.create_namespaced_job(namespace, job_body)
            logger.info(f"TaskRequest {name!r}: Job {name!r} created in {namespace!r}")
        except ApiException as e:
            if e.status == 409:
                # Job already exists
                logger.warning(
                    f"TaskRequest {name!r}: Job already exists, skipping creation"
                )
            elif e.status == 422:
                # Unprocessable Entity: the Job spec is invalid.
                logger.error(
                    f"TaskRequest {name!r}: Job spec rejected by API server (422): {e}"
                )
                self._set_status(
                    namespace=namespace,
                    name=name,
                    phase=FAILURE_PHASE,
                    message=f"Invalid Job spec: {e.reason}",
                    job_name="",
                    logger=logger,
                )
                return
            else:
                raise kopf.TemporaryError(
                    f"Failed to create Job for TaskRequest {name!r}: {e}", delay=10
                )

        self._set_status(
            namespace=namespace,
            name=name,
            phase=SCHEDULED_PHASE,
            message="",
            job_name=name,
            logger=logger,
        )

    def _sync_from_job(self, name: str, namespace: str, logger) -> None:
        """Sync TaskRequest status from an existing Job (used on resume)."""
        try:
            job = self._batch_v1.read_namespaced_job(name, namespace)
        except ApiException as e:
            if e.status == 404:
                logger.warning(f"TaskRequest {name!r}: Job not found on resume.")
            else:
                logger.error(
                    f"TaskRequest {name!r}: unexpected error reading Job "
                    f"(HTTP {e.status}): {e.reason}"
                )
            return

        conditions = self._extract_conditions(job.status)
        self._apply_conditions(name, namespace, conditions, logger)

    def _build_job(
        self,
        name: str,
        namespace: str,
        beta_star: dict,
        datasets: list[str],
        owner_uid: str,
    ) -> dict:
        """
        Build a Job manifest for a TaskRequest.

        The Job carries two scheduling annotations consumed by downstream
        pipeline components:
        - beta-star: serialised beta*(t).
        - datasets: serialised list of required dataset names.

        nodeAffinity is intentionally omitted here. It is injected by a Gatekeeper
        mutation webhook that reads the beta-star annotation and translates each
        property level into a `requiredDuringScheduling` matchExpression, realising
        the filter step `c_prop` of the formal model.
        """
        return {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {
                "name": name,
                "namespace": namespace,
                "labels": {
                    f"{self._config.job_label_prefix}/task-request": name,
                },
                "annotations": {
                    f"{self._config.job_annotation_prefix}/beta-star": json.dumps(
                        beta_star
                    ),
                    f"{self._config.job_annotation_prefix}/datasets": json.dumps(
                        datasets
                    ),
                },
                "ownerReferences": [
                    {
                        "apiVersion": f"{self._config.group}/{self._config.version}",
                        "kind": "TaskRequest",
                        "name": name,
                        "uid": owner_uid,
                        "controller": True,
                        "blockOwnerDeletion": True,
                    }
                ],
            },
            "spec": {
                "backoffLimit": 0,
                "template": {
                    "spec": {
                        "restartPolicy": "Never",
                        "containers": [
                            {
                                "name": "task",
                                # Blackbox placeholder: in a real implementation the
                                # task image would be supplied as metadata in the
                                # TaskRequest spec and validated by a dedicated
                                # image-service before the controller translates the
                                # request into a Job.
                                "image": "busybox:latest",
                                "command": [
                                    "sh",
                                    "-c",
                                    'echo "Task executed successfully" && sleep 5',
                                ],
                            }
                        ],
                    }
                },
            },
        }

    def _set_status(
        self, namespace: str, name: str, phase: str, message: str, job_name: str, logger
    ) -> None:
        """
        Patch the TaskRequest status via the /status subresource endpoint.

        Using the dedicated subresource ensures that only holders of the
        `taskrequests/status` RBAC verb can modify this field. Regular
        kubectl apply on the main resource silently ignores status changes.
        """
        try:
            self._custom_api.patch_namespaced_custom_object_status(
                group=self._config.group,
                version=self._config.version,
                namespace=namespace,
                plural=self._config.task_requests_plural,
                name=name,
                body={"status": {"phase": phase, "message": message, "job": job_name}},
            )
        except ApiException as e:
            if e.status == 404:
                logger.warning(
                    f"TaskRequest {name!r} not found when setting status to {phase!r}"
                )
            elif e.status == 422:
                logger.error(
                    f"TaskRequest {name!r} status patch rejected by API server, "
                    f"status schema mismatch: {e.reason}"
                )
            else:
                raise

    def _extract_conditions(self, job_status) -> list[dict]:
        """
        Return a normalised list of condition dicts from either a kopf body
        status dict or a V1JobStatus kubernetes client object.
        """
        if job_status is None:
            return []
        if isinstance(job_status, dict):
            return job_status.get("conditions") or []
        # V1JobStatus object from the kubernetes client
        if not job_status.conditions:
            return []
        return [{"type": c.type, "status": c.status} for c in job_status.conditions]

    def _apply_conditions(
        self, name: str, namespace: str, conditions: list[dict], logger
    ) -> None:
        """Translate Job conditions into a TaskRequest phase update."""
        for cond in conditions:
            cond_type = cond.get("type")
            cond_status = cond.get("status")
            if cond_type == "Complete" and cond_status == "True":
                self._set_status(
                    namespace,
                    name,
                    phase=SUCCESS_PHASE,
                    message="",
                    job_name=name,
                    logger=logger,
                )
                logger.info(f"TaskRequest {name!r} Succeeded")
                return
            if cond_type == "Failed" and cond_status == "True":
                message = cond.get("message") or "Job failed"
                self._set_status(
                    namespace,
                    name,
                    phase=FAILURE_PHASE,
                    message=message,
                    job_name=name,
                    logger=logger,
                )
                logger.info(f"TaskRequest {name!r} Failed: {message}")
                return
