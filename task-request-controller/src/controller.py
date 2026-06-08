import json

import kopf
from kubernetes import client
from kubernetes.client.exceptions import ApiException

from src.config import Config
from src.dataset_client import DatasetClient, DatasetNotFoundError, DatasetServiceError


class Controller:
    def __init__(
        self,
        batch_v1: client.BatchV1Api,
        custom_api: client.CustomObjectsApi,
        dataset_client: DatasetClient,
        config: Config,
    ):
        self._batch_v1 = batch_v1
        self._custom_api = custom_api
        self._dataset_client = dataset_client
        self._config = config

    def reconcile(self, name: str, namespace: str, body: dict, logger) -> None:
        """
        Idempotent reconciliation for a TaskRequest.

        - If the TaskRequest is already in a terminal phase (Succeeded/Failed),
          it is a no-op.
        - If it is Scheduled (Job exists), its status is synced from the Job.
        - Otherwise (Pending or no status yet), the full reconciliation runs:
          fetch beta(d) per dataset, compute beta*(t), create the Job.
        """
        phase = (body.get("status") or {}).get("phase")

        if phase in ("Succeeded", "Failed"):
            logger.info(
                f"TaskRequest {name!r} is in terminal phase {phase!r}, skipping"
            )
            return

        if phase == "Scheduled":
            logger.info(
                f"TaskRequest {name!r} is already Scheduled, syncing Job status"
            )
            self._sync_from_job(name, namespace, logger)
            return

        # Phase is None or Pending -> run full reconciliation.
        self._full_reconcile(name, namespace, body, logger)

    def sync_job_status(
        self, task_request_name: str, namespace: str, job_status, logger
    ) -> None:
        """
        Propagate a Job status change to the owning TaskRequest.

        Called by the kopf Job field-change handler. `job_status` may be
        a dict (from kopf body) or a V1JobStatus object (from direct API call).
        """
        conditions = self._extract_conditions(job_status)
        self._apply_conditions(task_request_name, namespace, conditions, logger)

    def _full_reconcile(self, name: str, namespace: str, body: dict, logger) -> None:
        """Fetch datasets, compute beta*(t), create Job, update status."""
        self._set_status(
            namespace, name, phase="Pending", message="", job_name="", logger=logger
        )

        spec = body.get("spec") or {}
        requirements: dict = spec.get("requirements") or {}
        datasets: list = spec.get("datasets") or []

        # Compute beta*(t) = LUB(beta(t), beta(d1), beta(d2), ...)
        try:
            beta_star = self._compute_beta_star(requirements, datasets)
        except DatasetNotFoundError as e:
            logger.error(f"TaskRequest {name!r}: {e}")
            self._set_status(
                namespace,
                name,
                phase="Failed",
                message=str(e),
                job_name="",
                logger=logger,
            )
            return
        except DatasetServiceError as e:
            # Transient error: ask kopf to retry after a delay.
            logger.warning(
                f"TaskRequest {name!r}: transient dataset service error — {e}"
            )
            raise kopf.TemporaryError(str(e), delay=30)

        logger.info(f"TaskRequest {name!r}: beta*(t) = {beta_star}")

        # Create Job 
        owner_uid = body["metadata"]["uid"]
        job_body = self._build_job(name, namespace, beta_star, owner_uid)

        try:
            self._batch_v1.create_namespaced_job(namespace, job_body)
            logger.info(f"TaskRequest {name!r}: Job {name!r} created in {namespace!r}")
        except ApiException as e:
            if e.status == 409:
                # Job already exists (e.g. controller restarted mid-reconciliation).
                logger.info(
                    f"TaskRequest {name!r}: Job already exists, skipping creation"
                )
            else:
                raise kopf.TemporaryError(
                    f"Failed to create Job for TaskRequest {name!r}: {e}", delay=15
                )

        self._set_status(
            namespace, name, phase="Scheduled", message="", job_name=name, logger=logger
        )

    def _sync_from_job(self, name: str, namespace: str, logger) -> None:
        """Sync TaskRequest status from an existing Job (used on resume)."""
        try:
            job = self._batch_v1.read_namespaced_job(name, namespace)
        except ApiException as e:
            if e.status == 404:
                logger.warning(
                    f"TaskRequest {name!r}: Job not found on resume, leaving status as-is"
                )
            else:
                logger.error(f"TaskRequest {name!r}: error reading Job — {e}")
            return

        conditions = self._extract_conditions(job.status)
        self._apply_conditions(name, namespace, conditions, logger)

    def _compute_beta_star(self, requirements: dict, datasets: list[str]) -> dict:
        """
        Compute the effective property class beta*(t).

        beta*(t) = LUB(beta(t), beta(d₁), beta(d₂), ...) computed component-wise as
        the maximum level for each property p ∈ P across the task requirements
        and all dataset requirements.
        """
        beta_star: dict[str, int] = dict(requirements)
        for dataset_name in datasets:
            dataset = self._dataset_client.get_dataset(dataset_name)
            for prop, level in (dataset.get("requirements") or {}).items():
                beta_star[prop] = max(beta_star.get(prop, 0), int(level))
        return beta_star

    def _build_job(
        self, name: str, namespace: str, beta_star: dict, owner_uid: str
    ) -> dict:
        """
        Build a Job manifest that realises the scheduling constraints for a TaskRequest.

        Pipeline position: this method is called by the controller after beta*(t) has
        been computed. The resulting Job carries two scheduling artefacts:

        1. nodeAffinity (requiredDuringScheduling): translates c_prop into native
           Kubernetes scheduling constraints. For each property p with beta*(t)[p] > 0,
           the node label `property.node.policydriven.unimi.it/p` must satisfy
           Gt beta*(t)[p]: 1, which is equivalent to ≥ beta*(t)[p] given that labels
           carry integer values. This realises the filter step of the formal model.

           An alternative pipeline design would have the controller emit the Job
           with only the beta* annotation and delegate the nodeAffinity injection to a
           Gatekeeper mutation webhook (Assign ConstraintTemplate). The two
           approaches are functionally equivalent; the direct approach is used here
           to keep the number of moving parts minimal.

        2. beta* annotation: the serialised effective property class is stored on the
           Job metadata so that the scheduler extender can read it during the
           prioritisation phase (φ_prop scoring) without recomputing it.
        """
        match_expressions = [
            {
                "key": f"{self._config.property_prefix}/{prop}",
                "operator": "Gt",
                "values": [str(level - 1)],
            }
            for prop, level in beta_star.items()
            if level > 0
        ]

        affinity = {}
        if match_expressions:
            affinity = {
                "nodeAffinity": {
                    "requiredDuringSchedulingIgnoredDuringExecution": {
                        "nodeSelectorTerms": [{"matchExpressions": match_expressions}]
                    }
                }
            }

        return {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {
                "name": name,
                "namespace": namespace,
                "labels": {
                    f"{self._config.task_request_ref_label_prefix}/task-request": name,
                },
                "annotations": {
                    f"{self._config.beta_star_annotation_prefix}/beta-star": json.dumps(
                        beta_star
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
                        **({"affinity": affinity} if affinity else {}),
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
                plural=self._config.plural,
                name=name,
                body={
                    "status": {"phase": phase, "message": message, "job": job_name}
                },
            )
        except ApiException as e:
            if e.status == 404:
                logger.warning(
                    f"TaskRequest {name!r} not found when setting status to {phase!r}"
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
                    phase="Succeeded",
                    message="",
                    job_name=name,
                    logger=logger,
                )
                logger.info(f"TaskRequest {name!r} → Succeeded")
                return
            if cond_type == "Failed" and cond_status == "True":
                message = cond.get("message") or "Job failed"
                self._set_status(
                    namespace,
                    name,
                    phase="Failed",
                    message=message,
                    job_name=name,
                    logger=logger,
                )
                logger.info(f"TaskRequest {name!r} → Failed: {message}")
                return
