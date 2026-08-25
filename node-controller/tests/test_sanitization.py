import unittest
from unittest.mock import MagicMock

from src.config import (
    Config,
    GROUP_DEFAULT,
    VERSION_DEFAULT,
    NODE_PROPERTIES_PLURAL_DEFAULT,
    ATTRIBUTE_PREFIX_DEFAULT,
    PROPERTY_PREFIX_DEFAULT,
    TRACE_PREFIX_DEFAULT,
    CONTEXTS_ANNOTATION_DEFAULT,
    SANITIZING_TAINT_DEFAULT,
    SCHEDULER_NAME_DEFAULT,
    SANITIZE_INTERVAL_SECONDS_DEFAULT,
    CLEAR_TRACES_SIMULATION_SECONDS_DEFAULT,
)
from src.sanitization import Sanitizer


def make_config():
    return Config(
        group=GROUP_DEFAULT,
        version=VERSION_DEFAULT,
        node_properties_plural=NODE_PROPERTIES_PLURAL_DEFAULT,
        attribute_prefix=ATTRIBUTE_PREFIX_DEFAULT,
        property_prefix=PROPERTY_PREFIX_DEFAULT,
        trace_prefix=TRACE_PREFIX_DEFAULT,
        contexts_annotation=CONTEXTS_ANNOTATION_DEFAULT,
        sanitizing_taint=SANITIZING_TAINT_DEFAULT,
        scheduler_name=SCHEDULER_NAME_DEFAULT,
        sanitize_interval_seconds=SANITIZE_INTERVAL_SECONDS_DEFAULT,
        clear_traces_simulation_seconds=CLEAR_TRACES_SIMULATION_SECONDS_DEFAULT,
        log_level="DEBUG",
        debug_mode=True,
    )


def make_logger():
    logger = MagicMock()
    logger.info = MagicMock()
    logger.error = MagicMock()
    logger.debug = MagicMock()
    return logger


def make_sanitizer(config):
    v1 = MagicMock()
    return Sanitizer(v1=v1, config=config)


def make_taint(key, effect="NoSchedule", value=None):
    t = MagicMock()
    t.key = key
    t.value = value
    t.effect = effect
    return t


class FakeNodeAPI:
    """
    Minimal stateful stand-in for read_node/patch_node. A plain
    MagicMock's read_node.return_value is a fixed snapshot: it would
    not reflect a patch_node call made moments earlier by the same
    test, which breaks any test exercising sanitize_node's full
    sequence (taint apply -> annotation clear -> taint remove), since
    each step re-reads the node to decide what to do next.
    """

    def __init__(self, annotations=None, taints=None):
        self.annotations = dict(annotations or {})
        self.taints = list(taints or [])  # list of {"key","value","effect"} dicts

    def read_node(self, _name):
        node = MagicMock()
        node.metadata.annotations = dict(self.annotations)
        node.spec.taints = [
            make_taint(t["key"], t.get("effect", "NoSchedule"), t.get("value"))
            for t in self.taints
        ]
        return node

    def patch_node(self, _name, body):
        if "taints" in body.get("spec", {}):
            self.taints = body["spec"]["taints"]
        for key, value in body.get("metadata", {}).get("annotations", {}).items():
            if value is None:
                self.annotations.pop(key, None)
            else:
                self.annotations[key] = value


def make_pod(name, scheduler_name, phase, node_name="n1"):
    pod = MagicMock()
    pod.metadata.name = name
    pod.spec.scheduler_name = scheduler_name
    pod.spec.node_name = node_name
    pod.status.phase = phase
    return pod


class TestSanitizeNode(unittest.TestCase):
    def setUp(self):
        self.config = make_config()
        self.sanitizer = make_sanitizer(self.config)
        self.logger = make_logger()
        self.key = f"{self.config.trace_prefix}/{self.config.contexts_annotation}"

    def _node(self, annotations=None, taints=None):
        node = MagicMock()
        node.metadata.annotations = annotations or {}
        node.spec.taints = taints or []
        return node

    def test_empty_lambda_is_untouched(self):
        self.sanitizer._v1.read_node.return_value = self._node(annotations={})
        self.sanitizer.sanitize_node("n1", self.logger)
        self.sanitizer._v1.patch_node.assert_not_called()

    def test_empty_list_lambda_is_untouched(self):
        self.sanitizer._v1.read_node.return_value = self._node(
            annotations={self.key: "[]"}
        )
        self.sanitizer.sanitize_node("n1", self.logger)
        self.sanitizer._v1.patch_node.assert_not_called()

    def test_active_pod_leaves_taint_applied_and_lambda_untouched(self):
        self.sanitizer._v1.read_node.return_value = self._node(
            annotations={self.key: '["Ford"]'}
        )
        self.sanitizer._v1.list_pod_for_all_namespaces.return_value = MagicMock(
            items=[make_pod("t1", self.config.scheduler_name, "Running")]
        )

        self.sanitizer.sanitize_node("n1", self.logger)

        # Taint applied (first patch_node call), Lambda(n) not cleared.
        patch_calls = self.sanitizer._v1.patch_node.call_args_list
        self.assertEqual(len(patch_calls), 1)
        self.assertIn("taints", patch_calls[0][0][1]["spec"])

    def _wire_fake(self, annotations=None, taints=None):
        fake = FakeNodeAPI(annotations=annotations, taints=taints)
        self.sanitizer._v1.read_node.side_effect = fake.read_node
        self.sanitizer._v1.patch_node.side_effect = fake.patch_node
        return fake

    def test_ignores_pods_from_other_schedulers(self):
        # A pod bound by the default scheduler (or a DaemonSet pod) must
        # not block sanitization: only our own scheduler's pods count.
        fake = self._wire_fake(annotations={self.key: '["Ford"]'})
        self.sanitizer._v1.list_pod_for_all_namespaces.return_value = MagicMock(
            items=[make_pod("kube-proxy-x", "default-scheduler", "Running")]
        )

        self.sanitizer.sanitize_node("n1", self.logger)

        # Full sequence should have completed: taint applied then
        # removed (2 taint patches) plus the annotation clear (1) = 3.
        patch_calls = self.sanitizer._v1.patch_node.call_args_list
        self.assertEqual(len(patch_calls), 3)
        self.assertEqual(fake.taints, [])
        self.assertNotIn(self.key, fake.annotations)

    def test_ignores_succeeded_and_failed_pods(self):
        fake = self._wire_fake(annotations={self.key: '["Ford"]'})
        self.sanitizer._v1.list_pod_for_all_namespaces.return_value = MagicMock(
            items=[
                make_pod("t1", self.config.scheduler_name, "Succeeded"),
                make_pod("t2", self.config.scheduler_name, "Failed"),
            ]
        )

        self.sanitizer.sanitize_node("n1", self.logger)

        # No active pods -> full sanitization completes (3 patches).
        self.assertEqual(len(self.sanitizer._v1.patch_node.call_args_list), 3)
        self.assertNotIn(self.key, fake.annotations)

    def test_full_sanitization_clears_lambda_and_removes_taint(self):
        fake = self._wire_fake(annotations={self.key: '["Ford"]'})
        self.sanitizer._v1.list_pod_for_all_namespaces.return_value = MagicMock(
            items=[]
        )

        self.sanitizer.sanitize_node("n1", self.logger)

        patch_calls = self.sanitizer._v1.patch_node.call_args_list
        self.assertEqual(len(patch_calls), 3)

        # 1st: taint applied
        self.assertEqual(
            patch_calls[0][0][1]["spec"]["taints"][-1]["key"],
            f"{self.config.trace_prefix}/{self.config.sanitizing_taint}",
        )
        # 2nd: Lambda(n) cleared
        self.assertIsNone(patch_calls[1][0][1]["metadata"]["annotations"][self.key])
        # 3rd: taint removed
        self.assertEqual(patch_calls[2][0][1]["spec"]["taints"], [])

        # End state, not just the intermediate patch bodies.
        self.assertEqual(fake.taints, [])
        self.assertNotIn(self.key, fake.annotations)

    def test_preserves_unrelated_existing_taints(self):
        fake = self._wire_fake(
            annotations={self.key: '["Ford"]'},
            taints=[{"key": "node.kubernetes.io/not-ready", "effect": "NoExecute"}],
        )
        self.sanitizer._v1.list_pod_for_all_namespaces.return_value = MagicMock(
            items=[]
        )

        self.sanitizer.sanitize_node("n1", self.logger)

        patch_calls = self.sanitizer._v1.patch_node.call_args_list
        # 1st call applies our taint alongside the pre-existing one.
        first_taints = patch_calls[0][0][1]["spec"]["taints"]
        self.assertEqual(len(first_taints), 2)
        self.assertTrue(
            any(t["key"] == "node.kubernetes.io/not-ready" for t in first_taints)
        )
        # End state (after taint removal) keeps only the unrelated taint.
        self.assertEqual(len(fake.taints), 1)
        self.assertEqual(fake.taints[0]["key"], "node.kubernetes.io/not-ready")


class TestSetSanitizingTaint(unittest.TestCase):
    def setUp(self):
        self.config = make_config()
        self.sanitizer = make_sanitizer(self.config)
        self.logger = make_logger()

    def _node(self, taints=None):
        node = MagicMock()
        node.spec.taints = taints or []
        return node

    def test_apply_when_absent(self):
        self.sanitizer._v1.read_node.return_value = self._node()
        self.sanitizer._set_sanitizing_taint("n1", True, self.logger)
        self.sanitizer._v1.patch_node.assert_called_once()
        body = self.sanitizer._v1.patch_node.call_args[0][1]
        self.assertEqual(
            body["spec"]["taints"],
            [
                {
                    "key": f"{self.config.trace_prefix}/{self.config.sanitizing_taint}",
                    "effect": "NoSchedule",
                }
            ],
        )

    def test_apply_when_already_present_is_noop(self):
        self.sanitizer._v1.read_node.return_value = self._node(
            taints=[
                make_taint(f"{self.config.trace_prefix}/{self.config.sanitizing_taint}")
            ]
        )
        self.sanitizer._set_sanitizing_taint("n1", True, self.logger)
        self.sanitizer._v1.patch_node.assert_not_called()

    def test_remove_when_present(self):
        self.sanitizer._v1.read_node.return_value = self._node(
            taints=[
                make_taint(f"{self.config.trace_prefix}/{self.config.sanitizing_taint}")
            ]
        )
        self.sanitizer._set_sanitizing_taint("n1", False, self.logger)
        self.sanitizer._v1.patch_node.assert_called_once()
        body = self.sanitizer._v1.patch_node.call_args[0][1]
        self.assertEqual(body["spec"]["taints"], [])

    def test_remove_when_already_absent_is_noop(self):
        self.sanitizer._v1.read_node.return_value = self._node()
        self.sanitizer._set_sanitizing_taint("n1", False, self.logger)
        self.sanitizer._v1.patch_node.assert_not_called()


class TestHasActivePods(unittest.TestCase):
    def setUp(self):
        self.config = make_config()
        self.sanitizer = make_sanitizer(self.config)
        self.logger = make_logger()

    def test_no_pods(self):
        self.sanitizer._v1.list_pod_for_all_namespaces.return_value = MagicMock(
            items=[]
        )
        self.assertFalse(self.sanitizer._has_active_pods("n1", self.logger))

    def test_running_pod_from_our_scheduler(self):
        self.sanitizer._v1.list_pod_for_all_namespaces.return_value = MagicMock(
            items=[make_pod("t1", self.config.scheduler_name, "Running")]
        )
        self.assertTrue(self.sanitizer._has_active_pods("n1", self.logger))

    def test_pending_pod_from_our_scheduler(self):
        self.sanitizer._v1.list_pod_for_all_namespaces.return_value = MagicMock(
            items=[make_pod("t1", self.config.scheduler_name, "Pending")]
        )
        self.assertTrue(self.sanitizer._has_active_pods("n1", self.logger))

    def test_other_scheduler_ignored(self):
        self.sanitizer._v1.list_pod_for_all_namespaces.return_value = MagicMock(
            items=[make_pod("kube-proxy-x", "default-scheduler", "Running")]
        )
        self.assertFalse(self.sanitizer._has_active_pods("n1", self.logger))

    def test_uses_correct_field_selector(self):
        self.sanitizer._v1.list_pod_for_all_namespaces.return_value = MagicMock(
            items=[]
        )
        self.sanitizer._has_active_pods("kind-worker", self.logger)
        self.sanitizer._v1.list_pod_for_all_namespaces.assert_called_once_with(
            field_selector="spec.nodeName=kind-worker"
        )
