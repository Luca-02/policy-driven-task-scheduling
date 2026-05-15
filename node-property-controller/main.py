import os

import kopf
from dotenv import load_dotenv
from kubernetes import client, config
from src.controller import Controller

load_dotenv()

GROUP = os.getenv("GROUP", "example.com")
VERSION = os.getenv("VERSION", "v1alpha1")
PLURAL = os.getenv("PLURAL", "node-property-definitions")

# Kubernetes API client
ctrl = None


@kopf.on.startup()
def startup(logger, **kwargs):
    """Initialize Kubernetes client and controller instance"""
    global ctrl
    
    try:
        config.load_incluster_config()
        logger.info("Loaded in-cluster kubeconfig")
    except config.ConfigException:
        config.load_kube_config()
        logger.info("Loaded local kubeconfig")

    ctrl = Controller(v1=client.CoreV1Api())
    logger.info("🚀 NodePropertyDefinition Controller started!")


# --------------------------------------------------
# NodePropertyDefinition handlers
# --------------------------------------------------

@kopf.on.resume(GROUP, VERSION, PLURAL)
@kopf.on.create(GROUP, VERSION, PLURAL)
@kopf.on.update(GROUP, VERSION, PLURAL)
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


@kopf.on.delete(GROUP, VERSION, PLURAL)
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
