import kopf

from dotenv import load_dotenv
from kubernetes import client, config

from src.config import Config
from src.controller import Controller
from src.dataset_service import DatasetService

load_dotenv()

cfg: Config = Config.from_env()
ctrl: Controller | None = None


@kopf.on.startup()
def startup(settings: kopf.OperatorSettings, logger, **kwargs):
    try:
        config.load_incluster_config()
        logger.info("Loaded in-cluster kubeconfig")
    except config.ConfigException:
        config.load_kube_config()
        logger.info("Loaded local kubeconfig")

    # Store kopf progress in annotations to avoid conflicts with our
    # custom status subresource fields.
    settings.persistence.progress_storage = kopf.AnnotationsProgressStorage(
        prefix=cfg.group
    )

    settings.peering.name = "task-request-controller"
    settings.peering.standalone = False
    settings.peering.priority = 100

    global ctrl
    ctrl = Controller(
        batch_v1=client.BatchV1Api(),
        custom_api=client.CustomObjectsApi(),
        dataset_service=DatasetService(
            base_url=cfg.dataset_service_url,
            ca_cert_file=cfg.ca_cert_file,
        ),
        config=cfg,
    )
    logger.info("🚀 TaskRequest Controller started!")


# ------------------------------------------------------------------
# TaskRequest handlers
# ------------------------------------------------------------------


@kopf.on.resume(cfg.group, cfg.version, cfg.task_requests_plural)
@kopf.on.create(cfg.group, cfg.version, cfg.task_requests_plural)
def on_task_request(body, reason, logger, **kwargs):
    name = body["metadata"]["name"]
    namespace = body["metadata"]["namespace"]
    spec = body.get("spec", {})

    if reason == "create":
        logger.info(
            f"🟢 TaskRequest {name!r} created in namespace {namespace!r} with spec: {spec!r}"
        )
    else:
        logger.info(
            f"🔵 TaskRequest {name!r} resumed in namespace {namespace!r} with spec: {spec!r}"
        )

    # Only reconcile TaskRequests in the configured namespace.
    if namespace != cfg.task_namespace:
        logger.info(
            f"Skipping TaskRequest {name!r}: namespace {namespace!r} is not {cfg.task_namespace!r}"
        )
        return

    if ctrl is not None:
        ctrl.reconcile(name, namespace, body, logger)


# ------------------------------------------------------------------
# Job handlers — propagate Job status back to the TaskRequest
# ------------------------------------------------------------------


@kopf.on.resume("batch", "v1", "jobs")
@kopf.on.field("batch", "v1", "jobs", field="status")
def on_job_status_changed(body, logger, **kwargs):
    name = body["metadata"]["name"]
    namespace = body["metadata"]["namespace"]
    status = body.get("status", {})

    # Only care about Jobs in the task namespace that were created by this controller.
    if namespace != cfg.task_namespace:
        logger.info(
            f"Skipping Job {name!r}: namespace {namespace!r} is not {cfg.task_namespace!r}"
        )
        return

    task_request_ref_label = f"{cfg.job_label_prefix}/{cfg.task_request_ref_label}"
    task_request_name = (body.get("metadata", {}).get("labels") or {}).get(
        task_request_ref_label
    )
    if not task_request_name:
        logger.info(f"Skipping Job {name!r}: missing label {task_request_ref_label!r}")
        return

    logger.info(
        f"🔄 Job {name!r} status changed, syncing TaskRequest {task_request_name!r}: {status}"
    )

    if ctrl is not None:
        ctrl.sync_job_status(task_request_name, namespace, status, logger)


# ------------------------------------------------------------------
# GeographicalGroup handlers
# ------------------------------------------------------------------


@kopf.on.resume(cfg.group, cfg.version, cfg.geographical_groups_plural)
@kopf.on.create(cfg.group, cfg.version, cfg.geographical_groups_plural)
@kopf.on.update(cfg.group, cfg.version, cfg.geographical_groups_plural)
def on_geographical_group_created_or_updated(body, reason, logger, **kwargs):
    name = body["metadata"]["name"]
    spec = body.get("spec", {})

    if reason == "create":
        logger.info(f"🟢 GeographicalGroup {name!r} created with spec: {spec!r}")
    elif reason == "update":
        logger.info(f"🟡 GeographicalGroup {name!r} updated with spec: {spec!r}")
    else:
        logger.info(f"🔵 GeographicalGroup {name!r} resumed with spec: {spec!r}")

    if ctrl is not None:
        ctrl.on_geographical_group_created_or_updated(name, spec, logger)


@kopf.on.delete(cfg.group, cfg.version, cfg.geographical_groups_plural)
def on_geographical_group_deleted(body, logger, **kwargs):
    name = body["metadata"]["name"]
    logger.info(f"🔴 GeographicalGroup {name!r} deleted")

    if ctrl is not None:
        ctrl.on_geographical_group_deleted(name, logger)
