import unittest
from unittest.mock import MagicMock

from src.controller import Controller, ATTRIBUTE_PREFIX, PROPERTY_PREFIX


# --------------------------------------------------
# Helpers
# --------------------------------------------------

def make_logger():
    logger = MagicMock()
    logger.info = MagicMock()
    logger.error = MagicMock()
    logger.debug = MagicMock()
    return logger


def make_ctrl():
    v1 = MagicMock()
    ctrl = Controller(v1=v1)
    return ctrl


def attr_labels(d):
    return {f"{ATTRIBUTE_PREFIX}/{k}": v for k, v in d.items()}


def prop_label(name):
    return f"{PROPERTY_PREFIX}/{name}"


def patched_labels(ctrl):
    """Return {node_name: {label_key: last_patched_value}} from all patch_node calls."""
    result = {}
    for args, _ in ctrl._v1.patch_node.call_args_list:
        node_name = args[0]
        result.setdefault(node_name, {}).update(args[1]["metadata"]["labels"])
    return result


# --------------------------------------------------
# Thesis example data and expected results
# --------------------------------------------------

SECURITY_SPEC = {
    "levels": [
        {"level": 1, "disjunction": [
            {"clause": [{"key": "cert", "operator": "Eq", "values": ["certC"]}]},
        ]},
        {"level": 2, "disjunction": [
            {"clause": [{"key": "cert", "operator": "Eq", "values": ["certB"]}]},
            {"clause": [{"key": "isolation", "operator": "Eq", "values": ["strict"]}]},
        ]},
        {"level": 3, "disjunction": [
            {"clause": [
                {"key": "cert", "operator": "In", "values": ["certA", "certB"]},
                {"key": "isolation", "operator": "Eq", "values": ["strict"]},
            ]},
        ]},
    ]
}

COMPUTATION_SPEC = {
    "levels": [
        {"level": 1, "disjunction": [
            {"clause": [{"key": "cpu", "operator": "Gte", "values": [4]}]},
        ]},
        {"level": 2, "disjunction": [
            {"clause": [{"key": "gpu", "operator": "Eq", "values": ["t4"]}]},
            {"clause": [{"key": "cpu", "operator": "Gte", "values": [8]}]},
        ]},
        {"level": 3, "disjunction": [
            {"clause": [
                {"key": "gpu", "operator": "In", "values": ["a100", "h100"]},
                {"key": "cpu", "operator": "Gte", "values": [16]},
            ]},
        ]},
    ]
}

NODE_ATTRS = {
    "n1": {"cert": "certA", "isolation": "strict", "gpu": "a100", "cpu": "16"},
    "n2": {"cert": "certB", "isolation": "standard", "gpu": "t4", "cpu": "8"},
    "n3": {"cert": "certC", "isolation": "standard", "cpu": "4"},
    "n4": {"cert": "certC", "isolation": "strict", "gpu": "a100", "cpu": "24"},
    "n5": {"cert": "certA", "isolation": "strict", "cpu": "4"},
}

EXPECTED = {
    "n1": {"security": 3, "computation": 3},
    "n2": {"security": 2, "computation": 2},
    "n3": {"security": 1, "computation": 1},
    "n4": {"security": 2, "computation": 3},
    "n5": {"security": 3, "computation": 1},
}


def load_nodes(ctrl, logger=None):
    logger = logger or make_logger()
    for name, attrs in NODE_ATTRS.items():
        ctrl.on_node_created_or_updated(name, attr_labels(attrs), logger)


def load_properties(ctrl, logger=None):
    logger = logger or make_logger()
    ctrl.on_property_created_or_updated("security", SECURITY_SPEC, logger)
    ctrl.on_property_created_or_updated("computation", COMPUTATION_SPEC, logger)


# --------------------------------------------------
# Controller testing
# --------------------------------------------------

class TestExtractNodeAttributes(unittest.TestCase):
    def test_strips_prefix(self):
        attrs = {"cert": "certA", "cpu": "8"}
        labels = attr_labels(attrs)
        self.assertEqual(Controller._extract_node_attributes(labels), attrs)

    def test_ignores_non_attribute_labels(self):
        attrs = {"cert": "certA"}
        labels = {
            **attr_labels(attrs),
            "kubernetes.io/hostname": "n1",
            prop_label("security"): "3",
        }
        self.assertEqual(Controller._extract_node_attributes(labels), attrs)

    def test_empty_labels(self):
        self.assertEqual(Controller._extract_node_attributes({}), {})

    def test_only_non_attribute_labels(self):
        labels = {"kubernetes.io/hostname": "n1"}
        self.assertEqual(Controller._extract_node_attributes(labels), {})


class TestParseNode(unittest.TestCase):
    def test_parses_attributes(self):
        node = Controller._parse_node("n1", attr_labels(NODE_ATTRS["n1"]))
        self.assertEqual(node.name, "n1")
        self.assertEqual(node.attributes, NODE_ATTRS["n1"])

    def test_properties_dict_starts_empty(self):
        node = Controller._parse_node("n1", attr_labels(NODE_ATTRS["n1"]))
        self.assertEqual(node.properties, {})

    def test_empty_labels(self):
        node = Controller._parse_node("nx", {})
        self.assertEqual(node.attributes, {})

    def test_non_attribute_labels_ignored(self):
        labels = {
            **attr_labels({"cert": "certA"}),
            "kubernetes.io/hostname": "n1",
            prop_label("security"): "3",
        }
        node = Controller._parse_node("n1", labels)
        self.assertEqual(node.attributes, {"cert": "certA"})

    def test_parses_existing_property_labels(self):
        labels = {
            **attr_labels({"cert": "certA"}),
            prop_label("security"): "3",
            prop_label("computation"): "2",
        }
        node = Controller._parse_node("n1", labels)
        self.assertEqual(node.properties["security"], 3)
        self.assertEqual(node.properties["computation"], 2)

    def test_non_integer_property_label_ignored(self):
        labels = {prop_label("security"): "notanumber"}
        node = Controller._parse_node("nx", labels)
        self.assertNotIn("security", node.properties)

class TestParseProperty(unittest.TestCase):
    def test_parses_security(self):
        prop = Controller._parse_property("security", SECURITY_SPEC)
        self.assertEqual(prop.name, "security")
        self.assertEqual(len(prop.levels), 3)

    def test_parses_computation(self):
        prop = Controller._parse_property("computation", COMPUTATION_SPEC)
        self.assertEqual(len(prop.levels), 3)

    def test_unknown_operator_raises_with_context(self):
        spec = {"levels": [{"level": 1, "disjunction": [
            {"clause": [{"key": "cert", "operator": "INVALID", "values": ["x"]}]},
        ]}]}
        with self.assertRaises(ValueError) as ctx:
            Controller._parse_property("test", spec)
        msg = str(ctx.exception)
        self.assertIn("Unknown operator", msg)

    def test_missing_key_raises_with_context(self):
        spec = {"levels": [{"level": 1, "disjunction": [
            {"clause": [{"operator": "Eq", "values": ["x"]}]},
        ]}]}
        with self.assertRaises(KeyError):
            Controller._parse_property("test", spec)

    def test_missing_operator_raises(self):
        spec = {"levels": [{"level": 1, "disjunction": [
            {"clause": [{"key": "cert", "values": ["x"]}]},
        ]}]}
        with self.assertRaises(KeyError):
            Controller._parse_property("test", spec)

    def test_empty_spec(self):
        self.assertEqual(Controller._parse_property("empty", {}).levels, [])


class TestOnPropertyCreatedOrUpdated(unittest.TestCase):
    def test_stored_in_state(self):
        ctrl = make_ctrl()
        ctrl.on_property_created_or_updated("security", SECURITY_SPEC, make_logger())
        self.assertIn("security", ctrl._properties)

    def test_all_nodes_patched_correct_levels(self):
        ctrl = make_ctrl()
        load_nodes(ctrl)
        ctrl._v1.patch_node.reset_mock()

        ctrl.on_property_created_or_updated("security", SECURITY_SPEC, make_logger())

        labels = patched_labels(ctrl)
        for name, expected in EXPECTED.items():
            self.assertEqual(
                labels[name][prop_label("security")],
                str(expected["security"]),
                msg=f"{name} security mismatch",
            )

    def test_node_properties_dict_updated(self):
        ctrl = make_ctrl()
        load_nodes(ctrl)
        ctrl.on_property_created_or_updated("security", SECURITY_SPEC, make_logger())

        for name, expected in EXPECTED.items():
            self.assertEqual(
                ctrl._nodes[name].properties.get("security"),
                expected["security"],
                msg=f"{name} node.properties['security'] mismatch",
            )

    def test_thesis_table_node_properties_dict(self):
        ctrl = make_ctrl()
        load_nodes(ctrl)
        load_properties(ctrl)

        for name, expected in EXPECTED.items():
            for prop_name, exp_level in expected.items():
                self.assertEqual(
                    ctrl._nodes[name].properties.get(prop_name),
                    exp_level,
                    msg=f"{name}.{prop_name}: expected {exp_level}",
                )

    def test_invalid_spec_logs_error_does_not_crash(self):
        ctrl = make_ctrl()
        logger = make_logger()
        bad_spec = {"levels": [{"level": 1, "disjunction": [
            {"clause": [{"key": "cert", "operator": "INVALID"}]},
        ]}]}
        ctrl.on_property_created_or_updated("bad", bad_spec, logger)

        logger.error.assert_called_once()
        self.assertNotIn("bad", ctrl._properties)
        ctrl._v1.patch_node.assert_not_called()

    def test_update_replaces_property_and_relabels(self):
        ctrl = make_ctrl()
        load_nodes(ctrl)
        ctrl.on_property_created_or_updated("security", SECURITY_SPEC, make_logger())
        ctrl._v1.patch_node.reset_mock()

        # Only certA → level 1, rest → level 0
        updated_spec = {"levels": [{"level": 1, "disjunction": [
            {"clause": [{"key": "cert", "operator": "Eq", "values": ["certA"]}]},
        ]}]}
        ctrl.on_property_created_or_updated("security", updated_spec, make_logger())

        labels = patched_labels(ctrl)
        self.assertEqual(labels["n1"][prop_label("security")], "1")
        self.assertEqual(labels["n5"][prop_label("security")], "1")
        self.assertEqual(labels["n2"][prop_label("security")], "0")
        self.assertEqual(labels["n3"][prop_label("security")], "0")
        self.assertEqual(labels["n4"][prop_label("security")], "0")

    def test_update_syncs_node_properties_dict(self):
        ctrl = make_ctrl()
        load_nodes(ctrl)
        ctrl.on_property_created_or_updated("security", SECURITY_SPEC, make_logger())

        updated_spec = {"levels": [{"level": 1, "disjunction": [
            {"clause": [{"key": "cert", "operator": "Eq", "values": ["certA"]}]},
        ]}]}
        ctrl.on_property_created_or_updated("security", updated_spec, make_logger())

        self.assertEqual(ctrl._nodes["n1"].properties["security"], 1)
        self.assertEqual(ctrl._nodes["n2"].properties["security"], 0)

    def test_no_nodes_no_patch(self):
        ctrl = make_ctrl()
        ctrl.on_property_created_or_updated("security", SECURITY_SPEC, make_logger())
        ctrl._v1.patch_node.assert_not_called()


class TestOnPropertyDeleted(unittest.TestCase):
    def test_removed_from_state(self):
        ctrl = make_ctrl()
        ctrl.on_property_created_or_updated("security", SECURITY_SPEC, make_logger())
        ctrl.on_property_deleted("security", make_logger())
        self.assertNotIn("security", ctrl._properties)

    def test_label_set_to_none_on_all_nodes(self):
        ctrl = make_ctrl()
        load_nodes(ctrl)
        ctrl.on_property_created_or_updated("security", SECURITY_SPEC, make_logger())
        ctrl._v1.patch_node.reset_mock()

        ctrl.on_property_deleted("security", make_logger())

        labels = patched_labels(ctrl)
        for name in NODE_ATTRS:
            self.assertIsNone(labels[name][prop_label("security")])

    def test_node_properties_dict_cleared(self):
        ctrl = make_ctrl()
        load_nodes(ctrl)
        ctrl.on_property_created_or_updated("security", SECURITY_SPEC, make_logger())
        ctrl.on_property_deleted("security", make_logger())

        for node in ctrl._nodes.values():
            self.assertNotIn("security", node.properties)

    def test_other_property_label_untouched(self):
        ctrl = make_ctrl()
        load_nodes(ctrl)
        load_properties(ctrl)
        ctrl._v1.patch_node.reset_mock()

        ctrl.on_property_deleted("security", make_logger())

        for args, _ in ctrl._v1.patch_node.call_args_list:
            for key in args[1]["metadata"]["labels"]:
                self.assertNotEqual(key, prop_label("computation"))

    def test_other_property_in_node_properties_dict_untouched(self):
        ctrl = make_ctrl()
        load_nodes(ctrl)
        load_properties(ctrl)
        ctrl.on_property_deleted("security", make_logger())

        for name, expected in EXPECTED.items():
            self.assertEqual(
                ctrl._nodes[name].properties.get("computation"),
                expected["computation"],
            )

    def test_delete_nonexistent_does_not_raise(self):
        ctrl = make_ctrl()
        ctrl.on_property_deleted("nonexistent", make_logger())


class TestOnNodeCreatedOrUpdated(unittest.TestCase):
    def test_node_added_to_state(self):
        ctrl = make_ctrl()
        ctrl.on_node_created_or_updated("n1", attr_labels(NODE_ATTRS["n1"]), make_logger())
        self.assertIn("n1", ctrl._nodes)

    def test_node_labeled_with_all_known_properties(self):
        ctrl = make_ctrl()
        load_properties(ctrl)
        ctrl.on_node_created_or_updated("n1", attr_labels(NODE_ATTRS["n1"]), make_logger())

        labels = patched_labels(ctrl)
        self.assertEqual(labels["n1"][prop_label("security")], "3")
        self.assertEqual(labels["n1"][prop_label("computation")], "3")

    def test_node_properties_dict_set(self):
        ctrl = make_ctrl()
        load_properties(ctrl)
        ctrl.on_node_created_or_updated("n1", attr_labels(NODE_ATTRS["n1"]), make_logger())

        self.assertEqual(ctrl._nodes["n1"].properties["security"], 3)
        self.assertEqual(ctrl._nodes["n1"].properties["computation"], 3)

    def test_no_properties_no_patch(self):
        ctrl = make_ctrl()
        ctrl.on_node_created_or_updated("n1", attr_labels(NODE_ATTRS["n1"]), make_logger())
        ctrl._v1.patch_node.assert_not_called()

    def test_unchanged_attributes_skips_relabeling(self):
        ctrl = make_ctrl()
        load_properties(ctrl)
        ctrl.on_node_created_or_updated("n1", attr_labels(NODE_ATTRS["n1"]), make_logger())
        ctrl._v1.patch_node.reset_mock()

        ctrl.on_node_created_or_updated("n1", attr_labels(NODE_ATTRS["n1"]), make_logger())

        ctrl._v1.patch_node.assert_not_called()

    def test_unchanged_attributes_with_property_label_skips_relabeling(self):
        """Simulates the controller's own patch triggering the node update event."""
        ctrl = make_ctrl()
        load_properties(ctrl)
        ctrl.on_node_created_or_updated("n1", attr_labels(NODE_ATTRS["n1"]), make_logger())
        ctrl._v1.patch_node.reset_mock()

        # Same attribute labels plus a property label added by the controller
        labels_with_prop = {
            **attr_labels(NODE_ATTRS["n1"]),
            prop_label("security"): "3",
        }
        ctrl.on_node_created_or_updated("n1", labels_with_prop, make_logger())

        ctrl._v1.patch_node.assert_not_called()

    def test_attribute_change_relabels(self):
        ctrl = make_ctrl()
        ctrl.on_property_created_or_updated("security", SECURITY_SPEC, make_logger())
        ctrl.on_node_created_or_updated("nx", attr_labels(NODE_ATTRS["n3"]), make_logger())
        ctrl._v1.patch_node.reset_mock()

        ctrl.on_node_created_or_updated("nx", attr_labels(NODE_ATTRS["n1"]), make_logger())

        labels = patched_labels(ctrl)
        self.assertEqual(labels["nx"][prop_label("security")], "3")
        self.assertEqual(ctrl._nodes["nx"].properties["security"], 3)

    def test_no_matching_attributes_gets_level_zero(self):
        ctrl = make_ctrl()
        ctrl.on_property_created_or_updated("security", SECURITY_SPEC, make_logger())
        ctrl.on_node_created_or_updated("nx", {}, make_logger())

        labels = patched_labels(ctrl)
        self.assertEqual(labels["nx"][prop_label("security")], "0")
        self.assertEqual(ctrl._nodes["nx"].properties["security"], 0)

    def test_stale_property_labels_removed(self):
        ctrl = make_ctrl()
        ctrl.on_property_created_or_updated("security", SECURITY_SPEC, make_logger())

        labels = {
            **attr_labels(NODE_ATTRS["n1"]),
            prop_label("oldprop"): "2",
        }
        ctrl.on_node_created_or_updated("n1", labels, make_logger())

        all_patches = patched_labels(ctrl)
        self.assertIsNone(all_patches["n1"][prop_label("oldprop")])

    def test_stale_label_removed_from_node_properties_dict(self):
        ctrl = make_ctrl()
        ctrl.on_property_created_or_updated("security", SECURITY_SPEC, make_logger())

        labels = {
            **attr_labels(NODE_ATTRS["n1"]),
            prop_label("oldprop"): "2",
        }
        ctrl.on_node_created_or_updated("n1", labels, make_logger())

        self.assertNotIn("oldprop", ctrl._nodes["n1"].properties)

    def test_known_property_label_not_treated_as_stale(self):
        ctrl = make_ctrl()
        ctrl.on_property_created_or_updated("security", SECURITY_SPEC, make_logger())

        labels = {
            **attr_labels(NODE_ATTRS["n1"]),
            prop_label("security"): "3",
        }
        ctrl.on_node_created_or_updated("n1", labels, make_logger())

        all_patches = patched_labels(ctrl)
        # security must be set, not removed
        self.assertIsNotNone(all_patches["n1"].get(prop_label("security")))
        self.assertNotEqual(all_patches["n1"].get(prop_label("security")), "None")

    def test_non_attribute_labels_ignored(self):
        ctrl = make_ctrl()
        ctrl.on_property_created_or_updated("security", SECURITY_SPEC, make_logger())

        labels = {
            **attr_labels(NODE_ATTRS["n1"]),
            "kubernetes.io/hostname": "n1",
            "node-role.kubernetes.io/worker": "",
        }
        ctrl.on_node_created_or_updated("n1", labels, make_logger())

        labels_patched = patched_labels(ctrl)
        self.assertEqual(labels_patched["n1"][prop_label("security")], "3")


class TestOnNodeDeleted(unittest.TestCase):
    def test_node_removed_from_state(self):
        ctrl = make_ctrl()
        load_nodes(ctrl)
        ctrl.on_node_deleted("n1", make_logger())
        self.assertNotIn("n1", ctrl._nodes)

    def test_other_nodes_unaffected(self):
        ctrl = make_ctrl()
        load_nodes(ctrl)
        ctrl.on_node_deleted("n1", make_logger())
        self.assertEqual(set(ctrl._nodes.keys()), {"n2", "n3", "n4", "n5"})

    def test_delete_nonexistent_does_not_raise(self):
        ctrl = make_ctrl()
        ctrl.on_node_deleted("nonexistent", make_logger())


class TestConcurrentOrderScenarios(unittest.TestCase):
    def _assert_example_table(self, ctrl):
        for name, expected in EXPECTED.items():
            for prop_name, exp_level in expected.items():
                self.assertEqual(
                    ctrl._nodes[name].properties.get(prop_name),
                    exp_level,
                    msg=f"{name}.{prop_name}: expected {exp_level}",
                )

    def test_properties_before_nodes(self):
        ctrl = make_ctrl()
        load_properties(ctrl)
        load_nodes(ctrl)
        self._assert_example_table(ctrl)

    def test_nodes_before_properties(self):
        ctrl = make_ctrl()
        load_nodes(ctrl)
        load_properties(ctrl)
        self._assert_example_table(ctrl)

    def test_interleaved(self):
        ctrl = make_ctrl()
        ctrl.on_node_created_or_updated("n1", attr_labels(NODE_ATTRS["n1"]), make_logger())
        ctrl.on_property_created_or_updated("security", SECURITY_SPEC, make_logger())
        ctrl.on_node_created_or_updated("n2", attr_labels(NODE_ATTRS["n2"]), make_logger())
        ctrl.on_property_created_or_updated("computation", COMPUTATION_SPEC, make_logger())
        for name in ["n3", "n4", "n5"]:
            ctrl.on_node_created_or_updated(name, attr_labels(NODE_ATTRS[name]), make_logger())
        self._assert_example_table(ctrl)
