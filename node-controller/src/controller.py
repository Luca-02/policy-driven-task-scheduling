from time import sleep
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
            key[len(prefix) :]: value
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
                    result[key[len(prefix) :]] = int(value)
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
            name=name,
            attributes=Controller._extract_node_attributes(labels, config),
            properties=Controller._extract_node_properties(labels, config),
        )

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
            prop = self._parse_property(name, spec)
        except Exception as e:
            logger.error(f"Property {name!r} has invalid spec, skipping: {e}")
            return

        self._properties[name] = prop
        logger.info(
            f"Property {name!r} loaded with {len(prop.levels)} levels, relabeling nodes"
        )

        # Relabel all nodes for the updated property
        label_key = f"{self._config.property_prefix}/{prop.name}"
        for node_name, node in self._nodes.items():
            level = node.evaluate_property(prop)
            self._patch_node_level(node_name, label_key, level, logger)

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
            self._patch_node_level(node_name, label_key, None, logger)

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
            key
            for key in labels
            if key.startswith(property_prefix)
            and key[len(property_prefix) :] not in self._properties
        ]
        for label_key in stale:
            prop_name = label_key[len(property_prefix) :]
            node.delete_property(prop_name)
            logger.info(f"Node {name!r}: removing stale property label {label_key!r}")
            self._patch_node_level(name, label_key, None, logger)

            # Relabel the node for all properties
        for prop in self._properties.values():
            label_key = f"{self._config.property_prefix}/{prop.name}"
            level = node.evaluate_property(prop)
            self._patch_node_level(node.name, label_key, level, logger)

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

    def _patch_node_level(
        self,
        node_name: str,
        label_key: str,
        level: int | None,
        logger,
    ):
        """
        Patch a node's level to set or remove a property level.

        Args:
            node_name: Name of the node to patch.
            label_key: The label key to set or remove.
            level: The level to set the label to, or None to remove it.
            logger: Logger object.
        """
        # If level is None or not a positive integer, remove the label by setting it to None
        level = str(level) if level is not None and level > 0 else None
        body = {"metadata": {"labels": {label_key: level}}}

        self._v1.patch_node(node_name, body)
        action = "removed" if level is None else f"set to: {level}"
        logger.info(f"Node {node_name!r} level {label_key!r} {action}")

    def sanitize_node(self, node_name: str, logger):
        """
        Implements Algorithm Sanitize(n) from the model:

            sanitizing(n) <- true       # n exits N
            WaitForCompletion(n)
            ClearResidualTraces(n)
            Lambda(n) <- {}
            sanitizing(n) <- false      # n re-enters N

        A node with Lambda(n) already empty is left untouched entirely (not even tainted):
        there is nothing to protect against, so there is nothing to sanitize. Because this
        method reruns on every timer tick for every node, WaitForCompletion is not a blocking
        wait: if active Pods are still present, the taint is left in place (n stays out of N)
        and this call simply returns, to be retried on the next tick.
        """
        node = self._v1.read_node(node_name)
        annotations = node.metadata.annotations or {}
        key = (
            f"{self._config.trace_prefix}/{self._config.contexts_annotation}"
        )
        trace = annotations.get(key, None)

        if not trace or trace == "[]":
            return

        # Step 1: Apply the sanitizing taint to prevent new Pods from being scheduled on this node.
        self._set_sanitizing_taint(node_name, True, logger)

        # Step 2: Wait for all active Pods scheduled by our own scheduler to complete.
        if self._has_active_pods(node_name, logger):
            logger.info(
                f"Node {node_name!r}: active Pod(s) still present, "
                f"deferring sanitization to a later tick"
            )
            return

        # Step 3: Clear residual traces (simulated in this prototype).
        self._clear_residual_traces(node_name, logger)

        # Step 4: Clear the Lambda(n) annotation to remove the node memory.
        self._clear_wall_contexts(node_name, key, logger)
        self._set_sanitizing_taint(node_name, False, logger)

        logger.info(f"Node {node_name!r}: sanitization complete")

    def _has_active_pods(self, node_name: str, logger) -> bool:
        """
        WaitForCompletion(n): true if at least one Pod scheduled by our
        own scheduler is still active (i.e. not Succeeded/Failed) on
        the node.

        Only Pods bound by our scheduler are considered: system/
        DaemonSet Pods (kube-proxy, CNI, ...) are permanently Running
        on every node and are not part of what Lambda(n) protects
        against.
        """
        pods = self._v1.list_pod_for_all_namespaces(
            field_selector=f"spec.nodeName={node_name}"
        )
        active = [
            pod
            for pod in pods.items
            if pod.spec.scheduler_name == self._config.scheduler_name
            and pod.status.phase not in ("Succeeded", "Failed")
        ]
        if active:
            logger.info(
                f"Node {node_name!r}: {len(active)} active pod(s): "
                f"{[pod.metadata.name for pod in active]}"
            )
        return bool(active)

    def _clear_residual_traces(self, node_name: str, logger):
        """
        ClearResidualTraces(n): simulated in this prototype, as the 
        actual implementation  would depend on the specific traces 
        being cleared and the system's architecture.
        """
        sleep(self._config.clear_traces_simulation_seconds)  # Simulate some work being done
        logger.info(f"Node {node_name!r}: clearing residual traces (simulated)")

    def _clear_wall_contexts(
        self,
        node_name: str,
        contexts_annotation_key: str,
        logger,
    ):
        """
        Lambda(n) <- {}: removes the node memory annotation entirely.
        """
        body = {"metadata": {"annotations": {contexts_annotation_key: None}}}
        self._v1.patch_node(node_name, body)
        logger.info(f"Node {node_name!r}: Lambda(n) cleared")

    def _set_sanitizing_taint(self, node_name: str, present: bool, logger):
        """
        Adds or removes the sanitizing taint on a node: the k8s-native
        mechanism implementing sanitizing(n). 
        
        While present, no new Pod is bound to the node by any scheduler 
        that honours standard taints, which is exactly:
        "n exits N for the duration of the operation".
        """
        node = self._v1.read_node(node_name)
        existing = node.spec.taints or []
        key = f"{self._config.trace_prefix}/{self._config.sanitizing_taint}"

        already_present = any(t.key == key for t in existing)
        if present == already_present:
            return

        if present:
            new_taints = [
                {"key": t.key, "value": t.value, "effect": t.effect} for t in existing
            ]
            new_taints.append({"key": key, "effect": "NoSchedule"})
        else:
            new_taints = [
                {"key": t.key, "value": t.value, "effect": t.effect}
                for t in existing
                if t.key != key
            ]

        self._v1.patch_node(node_name, {"spec": {"taints": new_taints}})
        logger.info(
            f"Node {node_name!r}: sanitizing taint {'applied' if present else 'removed'}"
        )
