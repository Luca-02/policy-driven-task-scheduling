import unittest
from unittest.mock import MagicMock

from src.config import Config
from src.controller import Controller

# --------------------------------------------------
# Helpers
# --------------------------------------------------


def make_config():
    return Config(
        group="node.thesis.io",
        version="v1",
        plural="nodes",
        attribute_prefix="attribute.node.thesis.io",
        property_prefix="property.node.thesis.io",
        log_level="info",
    )


def make_logger():
    logger = MagicMock()
    logger.info = MagicMock()
    logger.error = MagicMock()
    logger.debug = MagicMock()
    return logger


def make_ctrl(config):
    v1 = MagicMock()
    ctrl = Controller(v1=v1, config=config)
    return ctrl


def attr_labels(d, config):
    return {f"{config.attribute_prefix}/{k}": v for k, v in d.items()}


def prop_label(name, config):
    return f"{config.property_prefix}/{name}"


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
        {
            "level": 1,
            "disjunction": [
                {"clause": [{"key": "cert", "operator": "Eq", "values": ["certC"]}]},
            ],
        },
        {
            "level": 2,
            "disjunction": [
                {"clause": [{"key": "cert", "operator": "Eq", "values": ["certB"]}]},
                {
                    "clause": [
                        {"key": "isolation", "operator": "Eq", "values": ["strict"]}
                    ]
                },
            ],
        },
        {
            "level": 3,
            "disjunction": [
                {
                    "clause": [
                        {"key": "cert", "operator": "In", "values": ["certA", "certB"]},
                        {"key": "isolation", "operator": "Eq", "values": ["strict"]},
                    ]
                },
            ],
        },
    ]
}

COMPUTATION_SPEC = {
    "levels": [
        {
            "level": 1,
            "disjunction": [
                {"clause": [{"key": "cpu", "operator": "Gte", "values": [4]}]},
            ],
        },
        {
            "level": 2,
            "disjunction": [
                {"clause": [{"key": "gpu", "operator": "Eq", "values": ["t4"]}]},
                {"clause": [{"key": "cpu", "operator": "Gte", "values": [8]}]},
            ],
        },
        {
            "level": 3,
            "disjunction": [
                {
                    "clause": [
                        {"key": "gpu", "operator": "In", "values": ["a100", "h100"]},
                        {"key": "cpu", "operator": "Gte", "values": [16]},
                    ]
                },
            ],
        },
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


def load_nodes(ctrl, config, logger=None):
    logger = logger or make_logger()
    for name, attrs in NODE_ATTRS.items():
        ctrl.on_node_created_or_updated(name, attr_labels(attrs, config), logger)


def load_properties(ctrl, logger=None):
    logger = logger or make_logger()
    ctrl.on_property_created_or_updated("security", SECURITY_SPEC, logger)
    ctrl.on_property_created_or_updated("computation", COMPUTATION_SPEC, logger)


# --------------------------------------------------
# Controller testing
# --------------------------------------------------


class TestExtractNodeAttributes(unittest.TestCase):
    def setUp(self):
        self.config = make_config()

    def test_strips_prefix(self):
        attrs = {"cert": "certA", "cpu": "8"}
        labels = attr_labels(attrs, self.config)
        self.assertEqual(
            Controller._extract_node_attributes(labels, self.config), attrs
        )

    def test_ignores_non_attribute_labels(self):
        attrs = {"cert": "certA"}
        labels = {
            **attr_labels(attrs, self.config),
            "kubernetes.io/hostname": "n1",
            prop_label("security", self.config): "3",
        }
        self.assertEqual(
            Controller._extract_node_attributes(labels, self.config), attrs
        )

    def test_empty_labels(self):
        self.assertEqual(Controller._extract_node_attributes({}, self.config), {})

    def test_only_non_attribute_labels(self):
        labels = {"kubernetes.io/hostname": "n1"}
        self.assertEqual(Controller._extract_node_attributes(labels, self.config), {})


class TestParseNode(unittest.TestCase):
    def setUp(self):
        self.config = make_config()

    def test_parses_attributes(self):
        node = Controller._parse_node(
            "n1", attr_labels(NODE_ATTRS["n1"], self.config), self.config
        )
        self.assertEqual(node.name, "n1")
        self.assertEqual(node.attributes, NODE_ATTRS["n1"])

    def test_properties_dict_starts_empty(self):
        node = Controller._parse_node(
            "n1", attr_labels(NODE_ATTRS["n1"], self.config), self.config
        )
        self.assertEqual(node.properties, {})

    def test_empty_labels(self):
        node = Controller._parse_node("nx", {}, self.config)
        self.assertEqual(node.attributes, {})

    def test_non_attribute_labels_ignored(self):
        labels = {
            **attr_labels({"cert": "certA"}, self.config),
            "kubernetes.io/hostname": "n1",
            prop_label("security", self.config): "3",
        }
        node = Controller._parse_node("n1", labels, self.config)
        self.assertEqual(node.attributes, {"cert": "certA"})

    def test_parses_existing_property_labels(self):
        labels = {
            **attr_labels({"cert": "certA"}, self.config),
            prop_label("security", self.config): "3",
            prop_label("computation", self.config): "2",
        }
        node = Controller._parse_node("n1", labels, self.config)
        self.assertEqual(node.properties["security"], 3)
        self.assertEqual(node.properties["computation"], 2)

    def test_non_integer_property_label_ignored(self):
        labels = {prop_label("security", self.config): "notanumber"}
        node = Controller._parse_node("nx", labels, self.config)
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
        spec = {
            "levels": [
                {
                    "level": 1,
                    "disjunction": [
                        {
                            "clause": [
                                {"key": "cert", "operator": "INVALID", "values": ["x"]}
                            ]
                        },
                    ],
                }
            ]
        }
        with self.assertRaises(ValueError) as ctx:
            Controller._parse_property("test", spec)
        msg = str(ctx.exception)
        self.assertIn("Unknown operator", msg)

    def test_missing_key_raises_with_context(self):
        spec = {
            "levels": [
                {
                    "level": 1,
                    "disjunction": [
                        {"clause": [{"operator": "Eq", "values": ["x"]}]},
                    ],
                }
            ]
        }
        with self.assertRaises(KeyError):
            Controller._parse_property("test", spec)

    def test_missing_operator_raises(self):
        spec = {
            "levels": [
                {
                    "level": 1,
                    "disjunction": [
                        {"clause": [{"key": "cert", "values": ["x"]}]},
                    ],
                }
            ]
        }
        with self.assertRaises(KeyError):
            Controller._parse_property("test", spec)

    def test_empty_spec(self):
        self.assertEqual(Controller._parse_property("empty", {}).levels, [])


class TestOnPropertyCreatedOrUpdated(unittest.TestCase):
    def setUp(self):
        self.config = make_config()
        self.ctrl = make_ctrl(self.config)

    def test_stored_in_state(self):
        self.ctrl.on_property_created_or_updated(
            "security", SECURITY_SPEC, make_logger()
        )
        self.assertIn("security", self.ctrl._properties)

    def test_all_nodes_patched_correct_levels(self):
        load_nodes(self.ctrl, self.config)
        self.ctrl._v1.patch_node.reset_mock()

        self.ctrl.on_property_created_or_updated(
            "security", SECURITY_SPEC, make_logger()
        )

        labels = patched_labels(self.ctrl)
        for name, expected in EXPECTED.items():
            self.assertEqual(
                labels[name][prop_label("security", self.config)],
                str(expected["security"]),
                msg=f"{name} security mismatch",
            )

    def test_node_properties_dict_updated(self):
        load_nodes(self.ctrl, self.config)
        self.ctrl.on_property_created_or_updated(
            "security", SECURITY_SPEC, make_logger()
        )

        for name, expected in EXPECTED.items():
            self.assertEqual(
                self.ctrl._nodes[name].properties.get("security"),
                expected["security"],
                msg=f"{name} node.properties['security'] mismatch",
            )

    def test_thesis_table_node_properties_dict(self):
        load_nodes(self.ctrl, self.config)
        load_properties(self.ctrl)

        for name, expected in EXPECTED.items():
            for prop_name, exp_level in expected.items():
                self.assertEqual(
                    self.ctrl._nodes[name].properties.get(prop_name),
                    exp_level,
                    msg=f"{name}.{prop_name}: expected {exp_level}",
                )

    def test_invalid_spec_logs_error_does_not_crash(self):
        logger = make_logger()
        bad_spec = {
            "levels": [
                {
                    "level": 1,
                    "disjunction": [
                        {"clause": [{"key": "cert", "operator": "INVALID"}]},
                    ],
                }
            ]
        }
        self.ctrl.on_property_created_or_updated("bad", bad_spec, logger)

        logger.error.assert_called_once()
        self.assertNotIn("bad", self.ctrl._properties)
        self.ctrl._v1.patch_node.assert_not_called()

    def test_update_replaces_property_and_relabels(self):
        load_nodes(self.ctrl, self.config)
        self.ctrl.on_property_created_or_updated(
            "security", SECURITY_SPEC, make_logger()
        )
        self.ctrl._v1.patch_node.reset_mock()

        # Only certA → level 1, rest → level 0
        updated_spec = {
            "levels": [
                {
                    "level": 1,
                    "disjunction": [
                        {
                            "clause": [
                                {"key": "cert", "operator": "Eq", "values": ["certA"]}
                            ]
                        },
                    ],
                }
            ]
        }
        self.ctrl.on_property_created_or_updated(
            "security", updated_spec, make_logger()
        )

        labels = patched_labels(self.ctrl)
        self.assertEqual(labels["n1"][prop_label("security", self.config)], "1")
        self.assertEqual(labels["n5"][prop_label("security", self.config)], "1")
        self.assertIsNone(labels["n2"].get(prop_label("security", self.config)))
        self.assertIsNone(labels["n3"].get(prop_label("security", self.config)))
        self.assertIsNone(labels["n4"].get(prop_label("security", self.config)))

    def test_update_syncs_node_properties_dict(self):
        load_nodes(self.ctrl, self.config)
        self.ctrl.on_property_created_or_updated(
            "security", SECURITY_SPEC, make_logger()
        )

        updated_spec = {
            "levels": [
                {
                    "level": 1,
                    "disjunction": [
                        {
                            "clause": [
                                {"key": "cert", "operator": "Eq", "values": ["certA"]}
                            ]
                        },
                    ],
                }
            ]
        }
        self.ctrl.on_property_created_or_updated(
            "security", updated_spec, make_logger()
        )

        self.assertEqual(self.ctrl._nodes["n1"].properties["security"], 1)
        self.assertEqual(self.ctrl._nodes["n2"].properties["security"], 0)

    def test_no_nodes_no_patch(self):
        self.ctrl.on_property_created_or_updated(
            "security", SECURITY_SPEC, make_logger()
        )
        self.ctrl._v1.patch_node.assert_not_called()


class TestOnPropertyDeleted(unittest.TestCase):
    def setUp(self):
        self.config = make_config()
        self.ctrl = make_ctrl(self.config)

    def test_removed_from_state(self):
        self.ctrl.on_property_created_or_updated(
            "security", SECURITY_SPEC, make_logger()
        )
        self.ctrl.on_property_deleted("security", make_logger())
        self.assertNotIn("security", self.ctrl._properties)

    def test_label_set_to_none_on_all_nodes(self):
        load_nodes(self.ctrl, self.config)
        self.ctrl.on_property_created_or_updated(
            "security", SECURITY_SPEC, make_logger()
        )
        self.ctrl._v1.patch_node.reset_mock()

        self.ctrl.on_property_deleted("security", make_logger())

        labels = patched_labels(self.ctrl)
        for name in NODE_ATTRS:
            self.assertIsNone(labels[name][prop_label("security", self.config)])

    def test_node_properties_dict_cleared(self):
        load_nodes(self.ctrl, self.config)
        self.ctrl.on_property_created_or_updated(
            "security", SECURITY_SPEC, make_logger()
        )
        self.ctrl.on_property_deleted("security", make_logger())

        for node in self.ctrl._nodes.values():
            self.assertNotIn("security", node.properties)

    def test_other_property_label_untouched(self):
        load_nodes(self.ctrl, self.config)
        load_properties(self.ctrl)
        self.ctrl._v1.patch_node.reset_mock()

        self.ctrl.on_property_deleted("security", make_logger())

        for args, _ in self.ctrl._v1.patch_node.call_args_list:
            for key in args[1]["metadata"]["labels"]:
                self.assertNotEqual(key, prop_label("computation", self.config))

    def test_other_property_in_node_properties_dict_untouched(self):
        load_nodes(self.ctrl, self.config)
        load_properties(self.ctrl)
        self.ctrl.on_property_deleted("security", make_logger())

        for name, expected in EXPECTED.items():
            self.assertEqual(
                self.ctrl._nodes[name].properties.get("computation"),
                expected["computation"],
            )

    def test_delete_nonexistent_does_not_raise(self):
        self.ctrl.on_property_deleted("nonexistent", make_logger())


class TestOnNodeCreatedOrUpdated(unittest.TestCase):
    def setUp(self):
        self.config = make_config()
        self.ctrl = make_ctrl(self.config)

    def test_node_added_to_state(self):
        self.ctrl.on_node_created_or_updated(
            "n1", attr_labels(NODE_ATTRS["n1"], self.config), make_logger()
        )
        self.assertIn("n1", self.ctrl._nodes)

    def test_node_labeled_with_all_known_properties(self):
        load_properties(self.ctrl)
        self.ctrl.on_node_created_or_updated(
            "n1", attr_labels(NODE_ATTRS["n1"], self.config), make_logger()
        )

        labels = patched_labels(self.ctrl)
        self.assertEqual(labels["n1"][prop_label("security", self.config)], "3")
        self.assertEqual(labels["n1"][prop_label("computation", self.config)], "3")

    def test_node_properties_dict_set(self):
        load_properties(self.ctrl)
        self.ctrl.on_node_created_or_updated(
            "n1", attr_labels(NODE_ATTRS["n1"], self.config), make_logger()
        )

        self.assertEqual(self.ctrl._nodes["n1"].properties["security"], 3)
        self.assertEqual(self.ctrl._nodes["n1"].properties["computation"], 3)

    def test_no_properties_no_patch(self):
        self.ctrl.on_node_created_or_updated(
            "n1", attr_labels(NODE_ATTRS["n1"], self.config), make_logger()
        )
        self.ctrl._v1.patch_node.assert_not_called()

    def test_unchanged_attributes_skips_relabeling(self):
        load_properties(self.ctrl)
        self.ctrl.on_node_created_or_updated(
            "n1", attr_labels(NODE_ATTRS["n1"], self.config), make_logger()
        )
        self.ctrl._v1.patch_node.reset_mock()

        self.ctrl.on_node_created_or_updated(
            "n1", attr_labels(NODE_ATTRS["n1"], self.config), make_logger()
        )
        self.ctrl._v1.patch_node.assert_not_called()

    def test_unchanged_attributes_with_property_label_skips_relabeling(self):
        """Simulates the controller's own patch triggering the node update event."""
        load_properties(self.ctrl)
        self.ctrl.on_node_created_or_updated(
            "n1", attr_labels(NODE_ATTRS["n1"], self.config), make_logger()
        )
        self.ctrl._v1.patch_node.reset_mock()

        # Same attribute labels plus a property label added by the controller
        labels_with_prop = {
            **attr_labels(NODE_ATTRS["n1"], self.config),
            prop_label("security", self.config): "3",
        }
        self.ctrl.on_node_created_or_updated("n1", labels_with_prop, make_logger())

        self.ctrl._v1.patch_node.assert_not_called()

    def test_attribute_change_relabels(self):
        self.ctrl.on_property_created_or_updated(
            "security", SECURITY_SPEC, make_logger()
        )
        self.ctrl.on_node_created_or_updated(
            "nx", attr_labels(NODE_ATTRS["n3"], self.config), make_logger()
        )
        self.ctrl._v1.patch_node.reset_mock()

        self.ctrl.on_node_created_or_updated(
            "nx", attr_labels(NODE_ATTRS["n1"], self.config), make_logger()
        )

        labels = patched_labels(self.ctrl)
        self.assertEqual(labels["nx"][prop_label("security", self.config)], "3")
        self.assertEqual(self.ctrl._nodes["nx"].properties["security"], 3)

    def test_no_matching_attributes_gets_level_zero(self):
        self.ctrl.on_property_created_or_updated(
            "security", SECURITY_SPEC, make_logger()
        )
        self.ctrl.on_node_created_or_updated("nx", {}, make_logger())

        labels = patched_labels(self.ctrl)
        self.assertIsNone(labels["nx"].get(prop_label("security", self.config)))
        self.assertEqual(self.ctrl._nodes["nx"].properties["security"], 0)

    def test_stale_property_labels_removed(self):
        self.ctrl.on_property_created_or_updated(
            "security", SECURITY_SPEC, make_logger()
        )

        labels = {
            **attr_labels(NODE_ATTRS["n1"], self.config),
            prop_label("oldprop", self.config): "2",
        }
        self.ctrl.on_node_created_or_updated("n1", labels, make_logger())

        all_patches = patched_labels(self.ctrl)
        self.assertIsNone(all_patches["n1"][prop_label("oldprop", self.config)])

    def test_stale_label_removed_from_node_properties_dict(self):
        self.ctrl.on_property_created_or_updated(
            "security", SECURITY_SPEC, make_logger()
        )

        labels = {
            **attr_labels(NODE_ATTRS["n1"], self.config),
            prop_label("oldprop", self.config): "2",
        }
        self.ctrl.on_node_created_or_updated("n1", labels, make_logger())

        self.assertNotIn("oldprop", self.ctrl._nodes["n1"].properties)

    def test_known_property_label_not_treated_as_stale(self):
        self.ctrl.on_property_created_or_updated(
            "security", SECURITY_SPEC, make_logger()
        )

        labels = {
            **attr_labels(NODE_ATTRS["n1"], self.config),
            prop_label("security", self.config): "3",
        }
        self.ctrl.on_node_created_or_updated("n1", labels, make_logger())

        all_patches = patched_labels(self.ctrl)
        # security must be set, not removed
        self.assertIsNotNone(all_patches["n1"].get(prop_label("security", self.config)))
        self.assertNotEqual(
            all_patches["n1"].get(prop_label("security", self.config)), "None"
        )

    def test_non_attribute_labels_ignored(self):
        self.ctrl.on_property_created_or_updated(
            "security", SECURITY_SPEC, make_logger()
        )

        labels = {
            **attr_labels(NODE_ATTRS["n1"], self.config),
            "kubernetes.io/hostname": "n1",
            "node-role.kubernetes.io/worker": "",
        }
        self.ctrl.on_node_created_or_updated("n1", labels, make_logger())

        labels_patched = patched_labels(self.ctrl)
        self.assertEqual(labels_patched["n1"][prop_label("security", self.config)], "3")


class TestOnNodeDeleted(unittest.TestCase):
    def setUp(self):
        self.config = make_config()
        self.ctrl = make_ctrl(self.config)

    def test_node_removed_from_state(self):
        load_nodes(self.ctrl, self.config)
        self.ctrl.on_node_deleted("n1", make_logger())
        self.assertNotIn("n1", self.ctrl._nodes)

    def test_other_nodes_unaffected(self):
        load_nodes(self.ctrl, self.config)
        self.ctrl.on_node_deleted("n1", make_logger())
        self.assertEqual(set(self.ctrl._nodes.keys()), {"n2", "n3", "n4", "n5"})

    def test_delete_nonexistent_does_not_raise(self):
        self.ctrl.on_node_deleted("nonexistent", make_logger())


class TestConcurrentOrderScenarios(unittest.TestCase):
    def setUp(self):
        self.config = make_config()
        self.ctrl = make_ctrl(self.config)

    def _assert_example_table(self, ctrl):
        for name, expected in EXPECTED.items():
            for prop_name, exp_level in expected.items():
                self.assertEqual(
                    ctrl._nodes[name].properties.get(prop_name),
                    exp_level,
                    msg=f"{name}.{prop_name}: expected {exp_level}",
                )

    def test_properties_before_nodes(self):
        load_properties(self.ctrl)
        load_nodes(self.ctrl, self.config)
        self._assert_example_table(self.ctrl)

    def test_nodes_before_properties(self):
        load_nodes(self.ctrl, self.config)
        load_properties(self.ctrl)
        self._assert_example_table(self.ctrl)

    def test_interleaved(self):
        self.ctrl.on_node_created_or_updated(
            "n1", attr_labels(NODE_ATTRS["n1"], self.config), make_logger()
        )
        self.ctrl.on_property_created_or_updated(
            "security", SECURITY_SPEC, make_logger()
        )
        self.ctrl.on_node_created_or_updated(
            "n2", attr_labels(NODE_ATTRS["n2"], self.config), make_logger()
        )
        self.ctrl.on_property_created_or_updated(
            "computation", COMPUTATION_SPEC, make_logger()
        )
        for name in ["n3", "n4", "n5"]:
            self.ctrl.on_node_created_or_updated(
                name, attr_labels(NODE_ATTRS[name], self.config), make_logger()
            )
        self._assert_example_table(self.ctrl)
