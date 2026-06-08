import kopf
import random

from dotenv import load_dotenv
from kubernetes import client, config

from src.config import Config
from src.controller import Controller, TASK_REQUEST_LABEL
from src.dataset_client import DatasetClient

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
    settings.peering.priority = random.randint(0, 32767)

    settings.peering.standalone = False

    global ctrl
    ctrl = Controller(
        batch_v1=client.BatchV1Api(),
        custom_api=client.CustomObjectsApi(),
        dataset_client=DatasetClient(
            base_url=cfg.dataset_service_url,
            ca_cert_file=cfg.ca_cert_file,
        ),
        config=cfg,
    )
    logger.info("🚀 TaskRequest Controller started!")


# ------------------------------------------------------------------
# TaskRequest handlers
# ------------------------------------------------------------------


@kopf.on.resume(cfg.group, cfg.version, cfg.plural)
@kopf.on.create(cfg.group, cfg.version, cfg.plural)
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
def on_job_status_changed(body, reason, logger, **kwargs):
    name = body["metadata"]["name"]
    namespace = body["metadata"]["namespace"]
    status = body.get("status", {})

    # Only care about Jobs in the task namespace that were created by this controller.
    if namespace != cfg.task_namespace:
        return

    task_request_name = (body.get("metadata", {}).get("labels") or {}).get(
        TASK_REQUEST_LABEL
    )
    if not task_request_name:
        return

    logger.info(
        f"🔄 Job {name!r} status changed, syncing TaskRequest {task_request_name!r}"
    )

    if ctrl is not None:
        ctrl.sync_job_status(task_request_name, namespace, status, logger)
