import kopf

from dotenv import load_dotenv
from kubernetes import client, config

from src.config import Config
from src.controller import Controller

load_dotenv()

cfg: Config = Config.from_env()
ctrl: Controller | None = None

CONTROL_PLANE_LABELS = {
    "node-role.kubernetes.io/control-plane",
    "node-role.kubernetes.io/master",  # Legacy label
}


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

    settings.peering.name = "node-property-controller"
    settings.peering.standalone = False
    settings.peering.priority = 100

    global ctrl
    ctrl = Controller(v1=client.CoreV1Api(), config=cfg)
    logger.info("🚀 NodeProperty Controller started!")


# --------------------------------------------------
# NodeProperty handlers
# --------------------------------------------------


def on_property_created_or_updated(body, reason, logger, **kwargs):
    name = body["metadata"]["name"]
    spec = body.get("spec", {})

    if reason == "resume":
        logger.info(f"🔵 NodeProperty {name!r} resumed with spec: {spec}")
    elif reason == "create":
        logger.info(f"🟢 NodeProperty {name!r} created with spec: {spec}")
    elif reason == "update":
        logger.info(f"🟡 NodeProperty {name!r} updated with spec: {spec}")

    if ctrl is not None:
        ctrl.on_property_created_or_updated(name, spec, logger)


kopf.on.resume(
    cfg.group,
    cfg.version,
    cfg.node_properties_plural,
)(on_property_created_or_updated)

kopf.on.create(
    cfg.group,
    cfg.version,
    cfg.node_properties_plural,
)(on_property_created_or_updated)

# Ensure that the assumption of immutability of metadata is respected.
# This will mitigate the `Time-of-check to Time-of-use` race condition that can occur
# when updating metadata.
if cfg.debug_mode:
    kopf.on.update(
        cfg.group,
        cfg.version,
        cfg.node_properties_plural,
    )(on_property_created_or_updated)


@kopf.on.delete(cfg.group, cfg.version, cfg.node_properties_plural)
def on_property_deleted(body, logger, **kwargs):
    name = body["metadata"]["name"]
    logger.info(f"🔴 NodeProperty {name!r} deleted")

    if ctrl is not None:
        ctrl.on_property_deleted(name, logger)


# ------------------------------------------------------------------
# Node handlers
# ------------------------------------------------------------------


def on_node_created_or_updated(body, reason, logger, **kwargs):
    name = body["metadata"]["name"]
    labels = body["metadata"].get("labels") or {}

    # Skip control plane
    if any(l in labels for l in CONTROL_PLANE_LABELS):
        logger.info(f"Skipping control-plane node {name}")
        return

    if reason == "resume":
        logger.info(f"🔵 Node {name!r} resumed with labels: {labels}")
    elif reason == "create":
        logger.info(f"🟢 Node {name!r} created with labels: {labels}")
    elif reason == "update":
        logger.info(f"🟡 Node {name!r} updated with labels: {labels}")

    if ctrl is not None:
        ctrl.on_node_created_or_updated(name, labels, logger)


kopf.on.resume("", "v1", "nodes")(on_node_created_or_updated)
kopf.on.create("", "v1", "nodes")(on_node_created_or_updated)

# Ensure that the assumption of immutability of metadata is respected.
# This will mitigate the `Time-of-check to Time-of-use` race condition that can occur
# when updating metadata.
if cfg.debug_mode:
    kopf.on.update("", "v1", "nodes")(on_node_created_or_updated)


@kopf.on.delete("", "v1", "nodes")
def on_node_deleted(body, logger, **kwargs):
    name = body["metadata"]["name"]
    logger.info(f"🔴 Node {name!r} deleted")

    if ctrl is not None:
        ctrl.on_node_deleted(name, logger)


# ------------------------------------------------------------------
# Node sanitization timer
# ------------------------------------------------------------------

if cfg.sanitize_interval_seconds > 0:

    @kopf.timer("", "v1", "nodes", interval=cfg.sanitize_interval_seconds)
    def sanitize_node(body, logger, **kwargs):
        name = body["metadata"]["name"]
        labels = body["metadata"].get("labels") or {}

        # Control-plane nodes never run tasks, so Lambda(n) never applies to
        # them; skip rather than let sanitize_node no-op on an empty
        # annotation every single tick.
        if any(l in labels for l in CONTROL_PLANE_LABELS):
            logger.info(f"Skipping control-plane node {name} sanitization")
            return

        logger.info(f"🧹 Sanitizing node {name!r}")

        if ctrl is not None:
            ctrl.sanitize_node(name, logger)
