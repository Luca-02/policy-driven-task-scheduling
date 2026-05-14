import logging
import kopf

from kubernetes import client, config

GROUP = "thesis.io"
VERSION = "v1alpha1"
PLURAL = "node-property-definitions"

# Kubernetes API client
v1 = None


def print_cluster_nodes(logger):
    if v1 is None:
        logger.error("Kubernetes API client not initialized")
        return

    try:
        nodes = v1.list_node()

        logger.info(f"📦 Cluster nodes: {len(nodes.items)}")
        for node in nodes.items:
            logger.debug(f"{node.metadata.name}: {node.metadata.labels}")
    except Exception as e:
        logger.error(f"Error reading nodes: {e}")

# TODO: add controller also on node insertion or update or delete ecc

@kopf.on.startup()
def startup(logger, **kwargs):
    try:
        config.load_incluster_config()
        logging.info("Loaded in-cluster kubeconfig")
    except config.ConfigException:
        config.load_kube_config()
        logging.info("Loaded local kubeconfig")

    global v1
    v1 = client.CoreV1Api()
    logger.info("🚀 NodePropertyDefinition controller started")
    print_cluster_nodes(logger)


@kopf.on.create(GROUP, VERSION, PLURAL)
def on_create(name, spec, logger, **kwargs):
    logger.info(f"🟢 NEW CRD: {name}")
    logger.debug(f"spec: {spec}")


@kopf.on.update(GROUP, VERSION, PLURAL)
def on_update(name, spec, diff, logger, **kwargs):
    logger.info(f"🟡 UPDATED CRD: {name}")
    logger.debug(f"diff: {diff}")
    logger.debug(f"spec: {spec}")

@kopf.on.delete(GROUP, VERSION, PLURAL)
def on_delete(name, spec, logger, **kwargs):
    logger.info(f"🔴 DELETED CRD: {name}")
    logger.debug(f"spec: {spec}")