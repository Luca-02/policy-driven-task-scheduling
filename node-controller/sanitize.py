import logging

from dotenv import load_dotenv
from kubernetes import client, config

from src.config import Config
from src.sanitization import Sanitizer

load_dotenv()

# Control-plane nodes never run tasks, so Lambda(n) never applies to them;
# mirrors the skip logic in main.py's sanitize_node timer.
CONTROL_PLANE_LABELS = {
    "node-role.kubernetes.io/control-plane",
    "node-role.kubernetes.io/master",  # Legacy label
}


def main():
    cfg = Config.from_env()

    logging.basicConfig(level=cfg.log_level)
    logger = logging.getLogger("sanitize")

    try:
        config.load_incluster_config()
        logger.info("Loaded in-cluster kubeconfig")
    except config.ConfigException:
        config.load_kube_config()
        logger.info("Loaded local kubeconfig")

    v1 = client.CoreV1Api()
    sanitizer = Sanitizer(v1=v1, config=cfg)

    nodes = v1.list_node().items
    logger.info(f"Found {len(nodes)} node(s), starting manual sanitization")

    for node in nodes:
        name = node.metadata.name
        labels = node.metadata.labels or {}

        if any(l in labels for l in CONTROL_PLANE_LABELS):
            logger.info(f"Skipping control-plane node {name!r}")
            continue

        logger.info(f"Sanitizing node {name!r}")
        sanitizer.sanitize_node(name, logger)

    logger.info("Manual sanitization of all nodes finished")


if __name__ == "__main__":
    main()
