from time import sleep

from kubernetes import client

from src.config import Config


class Sanitizer:
    """
    Implements Algorithm Sanitize(n) from the model, decoupled from the
    Controller so it can be driven both by the periodic timer and by a
    standalone manual invocation (e.g. a one-off Job).
    """

    def __init__(self, v1: client.CoreV1Api, config: Config):
        self._v1: client.CoreV1Api = v1
        self._config: Config = config

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
        key = f"{self._config.trace_prefix}/{self._config.contexts_annotation}"
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
        sleep(
            self._config.clear_traces_simulation_seconds
        )  # Simulate some work being done
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
            return  # The taint is already in the desired state

        if present:
            # Add the sanitizing taint to the node's existing taints
            new_taints = [
                {"key": t.key, "value": t.value, "effect": t.effect} for t in existing
            ]
            new_taints.append({"key": key, "effect": "NoSchedule"})
        else:
            # Remove the sanitizing taint from the node's existing taints
            new_taints = [
                {"key": t.key, "value": t.value, "effect": t.effect}
                for t in existing
                if t.key != key
            ]

        self._v1.patch_node(node_name, {"spec": {"taints": new_taints}})
        logger.info(
            f"Node {node_name!r}: sanitizing taint {'applied' if present else 'removed'}"
        )
