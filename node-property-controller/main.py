import kopf
from kubernetes import client, config

from src.config import Config
from src.controller import Controller

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

    # # finalizer to ensure delete handlers run even if the CR is deleted concurrently
    # settings.persistence.finalizer = f"{cfg.group}/finalizer"

    # standard server-side progress storage in annotations
    settings.persistence.progress_storage = kopf.AnnotationsProgressStorage(
        prefix=cfg.group
    )

    # set a high priority for peering to ensure our handlers run before other controllers
    # that might react to the same events
    settings.peering.priority = 100

    global ctrl
    ctrl = Controller(v1=client.CoreV1Api(), config=cfg)
    logger.info("🚀 NodePropertyDefinition Controller started!")


# --------------------------------------------------
# NodePropertyDefinition handlers
# --------------------------------------------------


@kopf.on.resume(cfg.group, cfg.version, cfg.plural)
@kopf.on.create(cfg.group, cfg.version, cfg.plural)
@kopf.on.update(cfg.group, cfg.version, cfg.plural)
def on_property_created_or_updated(body, reason, logger, **kwargs):
    name = body["metadata"]["name"]
    spec = body.get("spec", {})
    if reason == "resume":
        logger.info(f"🔵 NodePropertyDefinition {name!r} resumed with spec: {spec}")
    elif reason == "create":
        logger.info(f"🟢 NodePropertyDefinition {name!r} created with spec: {spec}")
    elif reason == "update":
        logger.info(f"🟡 NodePropertyDefinition {name!r} updated with spec: {spec}")

    if ctrl is not None:
        ctrl.on_property_created_or_updated(name, spec, logger)


@kopf.on.delete(cfg.group, cfg.version, cfg.plural)
def on_property_deleted(body, logger, **kwargs):
    name = body["metadata"]["name"]
    logger.info(f"🔴 NodePropertyDefinition {name!r} deleted")

    if ctrl is not None:
        ctrl.on_property_deleted(name, logger)


# ------------------------------------------------------------------
# Node handlers
# ------------------------------------------------------------------


@kopf.on.resume("", "v1", "nodes")
@kopf.on.create("", "v1", "nodes")
@kopf.on.update("", "v1", "nodes")
def on_node_created_or_updated(body, reason, logger, **kwargs):
    name = body["metadata"]["name"]
    labels = body["metadata"].get("labels") or {}
    if reason == "resume":
        logger.info(f"🔵 Node {name!r} resumed with labels: {labels}")
    elif reason == "create":
        logger.info(f"🟢 Node {name!r} created with labels: {labels}")
    elif reason == "update":
        logger.info(f"🟡 Node {name!r} updated with labels: {labels}")

    if ctrl is not None:
        ctrl.on_node_created_or_updated(name, labels, logger)


@kopf.on.delete("", "v1", "nodes")
def on_node_deleted(body, logger, **kwargs):
    name = body["metadata"]["name"]
    logger.info(f"🔴 Node {name!r} deleted")

    if ctrl is not None:
        ctrl.on_node_deleted(name, logger)
