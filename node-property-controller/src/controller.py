from functools import wraps
from threading import Lock
from kubernetes import client

from src.config import Config
from src.models import Clause, Condition, Level, Node, Property


def _synchronized(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper
 

class Controller:
    def __init__(self, v1: client.CoreV1Api, config: Config):
        self._v1: client.CoreV1Api = v1
        self._config: Config = config
        self._nodes: dict[str, Node] = {}
        self._properties: dict[str, Property] = {}
        self._lock = Lock()

    @staticmethod
    def _extract_node_attributes(labels: dict, config: Config) -> dict[str, str]:
        """
        Extract node attributes from labels using the defined prefix.

        Args:
            labels: Dictionary of node labels and their prefix.
            config: Configuration object containing the attribute prefix.

        Returns:
            Dictionary of node attributes without the prefix.
        """
        prefix = f"{config.attribute_prefix}/"
        return {
            key[len(prefix):]: value
            for key, value in labels.items()
            if key.startswith(prefix)
        }

    @staticmethod
    def _extract_node_properties(labels: dict, config: Config) -> dict[str, int]:
        """
        Extract node properties from labels using the defined prefix.

        Args:
            labels: Dictionary of node labels and their prefix.
            config: Configuration object containing the property prefix.

        Returns:
            Dictionary of node properties without the prefix.
        """
        prefix = f"{config.property_prefix}/"
        result = {}
        for key, value in labels.items():
            if key.startswith(prefix):
                try:
                    result[key[len(prefix):]] = int(value)
                except (ValueError, TypeError):
                    pass
        return result

    @staticmethod
    def _parse_property(name: str, spec: dict) -> Property:
        """
        Parse a NodePropertyDefinition spec into a Property object.
        
        Args:
            name: Property name.
            spec: Property specification containing levels and conditions.

        Returns:
            A Property object representing the parsed specification.
        """
        levels = []
        for level in spec.get("levels", []):
            clauses = []
            for disjoint in level.get("disjunction", []):
                conditions = [
                    Condition(
                        key=cond["key"],
                        operator=cond["operator"],
                        values=cond.get("values", None),
                    )
                    for cond in disjoint.get("clause", [])
                ]
                clauses.append(Clause(conditions))
            levels.append(Level(level["level"], clauses))
        return Property(name, levels)

    @staticmethod
    def _parse_node(name: str, labels: dict, config: Config) -> Node:
        """
        Parse node labels into a Node object with attributes.
        Args:
            name: Node name.
            labels: Node labels.
            config: Configuration object containing the attribute and property prefixes.

        Returns:
            A Node object with extracted attributes.
        """
        return Node(
            name = name,
            attributes = Controller._extract_node_attributes(labels, config),
            properties = Controller._extract_node_properties(labels, config),
        )

    def _patch_node_label(self, node_name, label_key, value, logger):
        """
        Patch a node's label to set or remove a property level.
        
        Args:
            node_name: Name of the node to patch.
            label_key: The label key to set or remove.
            value: The value to set the label to, or None to remove it.
            logger: Logger object.
        """
        value = str(value) if value is not None else None
        body = {"metadata": {"labels": {label_key: value}}}
        self._v1.patch_node(node_name, body, async_req=True)
        action = "removed" if value is None else f"set to: {value}"
        logger.info(f"Node {node_name!r} label {label_key!r} {action}")

    @_synchronized
    def on_property_created_or_updated(self, name: str, spec: dict, logger):
        """
        Handle creation or update of a NodePropertyDefinition by parsing the spec,
        storing it in the controller's state, and relabeling all nodes accordingly.

        Args:
            name: Property name.
            spec: Property specification.
            logger: Logger object.
        """
        try:
            property = self._parse_property(name, spec)
        except Exception as e:
            logger.error(f"Property {name!r} has invalid spec, skipping: {e}")
            return

        self._properties[name] = property
        logger.info(f"Property {name!r} loaded with {len(property.levels)} levels, relabeling nodes")

        # Relabel all nodes for the updated property
        label_key = f"{self._config.property_prefix}/{property.name}"
        for node_name, node in self._nodes.items():
            level = node.evaluate_property(property)
            self._patch_node_label(node_name, label_key, level, logger)

    @_synchronized
    def on_property_deleted(self, name: str, logger):
        """
        Handle deletion of a NodePropertyDefinition by removing it from the controller's state
        and cleaning up the corresponding labels from all nodes.

        Args:
            name: Property name.
            logger: Logger object.
        """
        self._properties.pop(name, None)
        logger.info(f"Property {name!r} removed, cleaning up node labels")

        # Remove the property label from all nodes
        label_key = f"{self._config.property_prefix}/{name}"
        for node_name, node in self._nodes.items():
            node.delete_property(name)
            self._patch_node_label(node_name, label_key, None, logger)

    @_synchronized
    def on_node_created_or_updated(self, name: str, labels: dict, logger):
        """
        Handle creation or update of a Node by parsing its labels, storing it in the controller's state,
        and relabeling it according to all defined properties.

        Args:
            name: Node name.
            labels: Node labels.
            logger: Logger object.
        """
        node = self._parse_node(name, labels, self._config)

        existing = self._nodes.get(node.name)
        if existing is not None and existing.attributes == node.attributes:
            logger.info(f"Node {node.name!r}: attributes unchanged, skipping")
            return

        self._nodes[name] = node
        logger.info(f"Node {name!r} loaded, evaluating properties")

        # Remove stale property labels that no longer apply
        property_prefix = f"{self._config.property_prefix}/"
        stale = [
            key for key in labels
            if key.startswith(property_prefix)
               and key[len(property_prefix):] not in self._properties
        ]
        for label_key in stale:
            prop_name = label_key[len(property_prefix):]
            node.delete_property(prop_name)
            logger.info(f"Node {name!r}: removing stale property label {label_key!r}")
            self._patch_node_label(name, label_key, None, logger)

            # Relabel the node for all properties
        for property in self._properties.values():
            label_key = f"{self._config.property_prefix}/{property.name}"
            level = node.evaluate_property(property)
            self._patch_node_label(node.name, label_key, level, logger)

    @_synchronized
    def on_node_deleted(self, name: str, logger):
        """
        Handle deletion of a Node by removing it from the controller's state.

        Args:
            name: Node name.
            logger: Logger object.
        """
        self._nodes.pop(name, None)
        logger.info(f"Node {name!r} removed from state")
