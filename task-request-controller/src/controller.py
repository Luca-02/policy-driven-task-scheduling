from functools import wraps
from threading import Lock

import kopf

from kubernetes import client
from kubernetes.client.exceptions import ApiException

from src.config import Config
from src.dataset_service import (
    DatasetService,
    DatasetNotFoundError,
    DatasetServiceError,
)
from src.geo import GeographicGroup
from src.annotation import compute_effective_beta, compute_effective_geo
from src.job_builder import JobBuilder

COMPLETE_PHASE = "Complete"
FAILURE_PHASE = "Failed"
SCHEDULED_PHASE = "Scheduled"
PENDING_PHASE = "Pending"


def _synchronized(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


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
        self._geo_groups: dict[str, GeographicGroup] = {}
        self._lock = Lock()

    @_synchronized
    def reconcile(self, name: str, namespace: str, body: dict, logger):
        """
        Idempotent reconciliation for a TaskRequest.

        - If the TaskRequest is already in a terminal phase (Complete/Failed),
          it is a no-op.
        - If it is Scheduled (Job exists), its status is synced from the Job.
        - Otherwise (Pending or no status yet), the full reconciliation runs.

        Args:
            name: The name of the TaskRequest.
            namespace: The namespace of the TaskRequest.
            body: The full body of the TaskRequest resource.
            logger: Logger object.
        """
        phase = body.get("status", {}).get("phase")

        if phase in (COMPLETE_PHASE, FAILURE_PHASE):
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

    @_synchronized
    def sync_job_status(
        self, task_request_name: str, namespace: str, job_status: dict, logger
    ):
        """Propagate a Job status change to the related TaskRequest."""
        conditions = self._extract_conditions(job_status)
        self._apply_conditions(task_request_name, namespace, conditions, logger)

    @_synchronized
    def on_geographical_group_created_or_updated(self, name: str, spec: dict, logger):
        """
        Handle creation or update of a GeographicalGroup by storing it in-memory registry.

        Args:
            name: GeographicalGroup name.
            spec: GeographicalGroup spec, containing 'locations' and 'includes'.
            logger: Logger object.
        """
        locations = spec.get("locations", []) or []
        includes = spec.get("includes", []) or []
        self._geo_groups[name] = GeographicGroup(name, locations, includes)
        logger.info(
            f"GeographicalGroup {name!r} loaded: {len(locations)} locations, "
            f"{len(includes)} includes"
        )

    @_synchronized
    def on_geographical_group_deleted(self, name: str, logger):
        """
        Handle deletion of a GeographicalGroup by removing it from the in-memory registry.

        Args:
            name: GeographicalGroup name.
            logger: Logger object.
        """
        self._geo_groups.pop(name, None)
        logger.info(f"GeographicalGroup {name!r} removed from registry")

    def _full_reconcile(self, name: str, namespace: str, body: dict, logger):
        """
        Full reconciliation pipeline for a new or Pending TaskRequest:
            1. Set phase to Pending
            2. Fetch all required datasets in one pass
            3. Compute `beta*(t)`
            4. Compute `geo*(t)`, and if is empty (no node can satisfy it) fail
            5. Create the Job with TaskRequest reference and dataset annotations
            6. Set phase to Scheduled
        """
        # Set phase to Pending at the start of reconciliation
        self._set_status(
            namespace=namespace,
            name=name,
            phase=PENDING_PHASE,
            message="",
            job_name="",
            logger=logger,
        )

        spec = body.get("spec", {})
        requirements: dict = spec.get("requirements", {})
        datasets: list = spec.get("datasets", [])
        geo: str | None = spec.get("geo")

        try:
            datasets_data = self._dataset_service.get_all_datasets(datasets)
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
            logger.warning(f"TaskRequest {name!r} transient dataset service error: {e}")
            raise kopf.TemporaryError(str(e), delay=10)

        dataset_requirements = [d.get("requirements") for d in datasets_data]
        beta_star = compute_effective_beta(requirements, dataset_requirements)
        logger.info(f"TaskRequest {name!r}: computed beta*(t) = {beta_star}")

        dataset_geos = [d.get("geo") for d in datasets_data]
        geo_star = compute_effective_geo(geo, dataset_geos, self._geo_groups)
        logger.info(f"TaskRequest {name!r}: computed geo*(t) = {geo_star}")

        # If geo*(t) is empty, it means there is no intersection between the TaskRequest's geo(t)
        # and the datasets geo(d), so we cannot schedule the Job. We log an error and set the
        # TaskRequest phase to Failed.
        if geo_star is not None and len(geo_star) == 0:
            message = (
                f"geo*(t) is empty: there are empty intersections between each dataset's "
                f"geo(d)={dataset_geos!r} and the TaskRequest's geo(t)={geo!r}."
            )
            logger.error(f"TaskRequest {name!r}: {message}")
            self._set_status(
                namespace=namespace,
                name=name,
                phase=FAILURE_PHASE,
                message=message,
                job_name="",
                logger=logger,
            )
            return

        owner_uid = body["metadata"]["uid"]
        job = (
            JobBuilder(config=self._config)
            .set_name(name)
            .set_namespace(namespace)
            .set_beta_star(beta_star)
            .set_geo_star(geo_star)
            .set_datasets(datasets)
            .set_owner(owner_uid)
            .build()
        )

        try:
            self._batch_v1.create_namespaced_job(namespace, job)
            logger.info(f"TaskRequest {name!r}: Job {name!r} created in {namespace!r}")
        except ApiException as e:
            if e.status == 409:
                # Job already exists.
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

        # Set status to Scheduled after Job creation
        self._set_status(
            namespace=namespace,
            name=name,
            phase=SCHEDULED_PHASE,
            message="",
            job_name=name,
            logger=logger,
        )

    def _sync_from_job(self, name: str, namespace: str, logger) -> None:
        """Sync TaskRequest status from an existing Job."""
        try:
            job: client.V1Job = self._batch_v1.read_namespaced_job(name, namespace)
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

    def _set_status(
        self,
        namespace: str,
        name: str,
        phase: str,
        message: str,
        job_name: str,
        logger,
    ) -> None:
        """Patch the TaskRequest status via the /status subresource endpoint."""
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

    def _extract_conditions(
        self, job_status: dict | client.V1JobStatus | None
    ) -> list[client.V1JobCondition]:
        """
        Return a normalised list of condition dicts from either a kopf body
        status dict or a V1JobStatus kubernetes client object.
        """
        if job_status is None:
            return []

        if isinstance(job_status, dict):
            return [
                client.V1JobCondition(
                    type=c.get("type"),
                    status=c.get("status"),
                    message=c.get("message"),
                    reason=c.get("reason"),
                    last_probe_time=c.get("lastProbeTime"),
                    last_transition_time=c.get("lastTransitionTime"),
                )
                for c in job_status.get("conditions", [])
            ]

        return job_status.conditions or []

    def _apply_conditions(
        self, name: str, namespace: str, conditions: list[client.V1JobCondition], logger
    ) -> None:
        """Translate Job conditions into a TaskRequest phase update."""
        for cond in conditions:
            if cond.type == COMPLETE_PHASE and cond.status == "True":
                message = cond.message or "Job completed successfully"
                self._set_status(
                    namespace,
                    name,
                    phase=COMPLETE_PHASE,
                    message=message,
                    job_name=name,
                    logger=logger,
                )
                logger.info(f"TaskRequest {name!r} Complete: {message}")
                return
            if cond.type == FAILURE_PHASE and cond.status == "True":
                message = cond.message or "Job failed"
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
