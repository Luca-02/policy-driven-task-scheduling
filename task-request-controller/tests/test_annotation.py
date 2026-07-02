import unittest

from src.geo import GeographicGroup
from src.annotation import (
    compute_effective_beta,
    compute_effective_geo,
    compute_static_nodes,
)


class TestComputeEffectiveBeta(unittest.TestCase):
    def test_no_datasets_returns_task_requirements(self):
        result = compute_effective_beta({"security": 2, "computation": 1}, [])
        self.assertEqual(result, {"security": 2, "computation": 1})

    def test_empty_task_and_no_datasets(self):
        self.assertEqual(compute_effective_beta({}, []), {})

    def test_dataset_raises_existing_property(self):
        result = compute_effective_beta({"security": 1}, [{"security": 2}])
        self.assertEqual(result["security"], 2)

    def test_task_requirement_prevails_over_dataset(self):
        result = compute_effective_beta({"security": 3}, [{"security": 1}])
        self.assertEqual(result["security"], 3)

    def test_dataset_introduces_new_property(self):
        result = compute_effective_beta({"security": 1}, [{"computation": 3}])
        self.assertEqual(result, {"security": 1, "computation": 3})

    def test_multiple_datasets_lub(self):
        result = compute_effective_beta(
            {"security": 1, "computation": 2},
            [{"security": 2, "computation": 1}, {"security": 1, "computation": 3}],
        )
        self.assertEqual(result, {"security": 2, "computation": 3})

    def test_null_requirements_dict_ignored(self):
        result = compute_effective_beta({"security": 2}, [None])
        self.assertEqual(result, {"security": 2})

    def test_level_zero_does_not_lower_task_requirement(self):
        result = compute_effective_beta({"security": 2}, [{"security": 0}])
        self.assertEqual(result["security"], 2)

    def test_does_not_mutate_beta_t(self):
        beta_t = {"security": 1}
        compute_effective_beta(beta_t, [{"computation": 3}])
        self.assertNotIn("computation", beta_t)


EU = GeographicGroup("EU", ["eu-north", "eu-south", "eu-east", "eu-west"], [])
US = GeographicGroup("US", ["us-north", "us-south", "us-east", "us-west"], [])
OECD = GeographicGroup("OECD", [], ["EU", "US"])

GEO_REGISTRY = {g.name: g for g in [EU, US, OECD]}


class TestComputeEffectiveGeo(unittest.TestCase):
    def test_all_omega_returns_none(self):
        self.assertIsNone(compute_effective_geo(None, [None, None], GEO_REGISTRY))

    def test_no_geo_t_no_datasets_returns_none(self):
        self.assertIsNone(compute_effective_geo(None, [], GEO_REGISTRY))

    def test_all_unknown_groups_returns_none(self):
        # All named groups are missing from registry: all skipped, no constraint
        self.assertIsNone(
            compute_effective_geo("UNKNOWN", ["ALSO_UNKNOWN"], GEO_REGISTRY)
        )

    def test_only_geo_t(self):
        result = compute_effective_geo("EU", [], GEO_REGISTRY)
        self.assertEqual(result, EU.resolve(GEO_REGISTRY))

    def test_only_dataset_geo(self):
        result = compute_effective_geo(None, ["EU"], GEO_REGISTRY)
        self.assertEqual(result, EU.resolve(GEO_REGISTRY))

    def test_geo_t_omega_dataset_geo_eu(self):
        result = compute_effective_geo(None, ["EU"], GEO_REGISTRY)
        self.assertEqual(result, EU.resolve(GEO_REGISTRY))

    def test_same_group_on_task_and_dataset(self):
        result = compute_effective_geo("EU", ["EU"], GEO_REGISTRY)
        self.assertEqual(result, EU.resolve(GEO_REGISTRY))

    def test_task_eu_dataset_oecd_result_is_eu(self):
        result = compute_effective_geo("EU", ["OECD"], GEO_REGISTRY)
        self.assertEqual(result, EU.resolve(GEO_REGISTRY))

    def test_task_oecd_dataset_eu_result_is_eu(self):
        result = compute_effective_geo("OECD", ["EU"], GEO_REGISTRY)
        self.assertEqual(result, EU.resolve(GEO_REGISTRY))

    def test_disjoint_groups_returns_empty_set(self):
        result = compute_effective_geo("EU", ["US"], GEO_REGISTRY)
        self.assertEqual(result, set())

    def test_multiple_datasets_intersection(self):
        result = compute_effective_geo("OECD", ["EU", "US"], GEO_REGISTRY)
        self.assertEqual(result, set())

    def test_dataset_omega_does_not_constrain(self):
        result = compute_effective_geo("EU", [None], GEO_REGISTRY)
        self.assertEqual(result, EU.resolve(GEO_REGISTRY))

    def test_omega_mixed_with_constraint(self):
        result = compute_effective_geo(None, [None, "EU", None], GEO_REGISTRY)
        self.assertEqual(result, EU.resolve(GEO_REGISTRY))

    def test_first_group_empty_intersection_not_overwritten(self):
        empty = GeographicGroup("EMPTY", [], [])
        registry = {**GEO_REGISTRY, "EMPTY": empty}
        result = compute_effective_geo("EMPTY", ["EU"], registry)
        self.assertEqual(result, set())

    def test_unknown_geo_t_skipped(self):
        # Unknown task geo is skipped
        result = compute_effective_geo("UNKNOWN", ["EU"], GEO_REGISTRY)
        self.assertEqual(result, EU.resolve(GEO_REGISTRY))

    def test_unknown_dataset_geo_skipped(self):
        # Unknown dataset geo is skipped
        result = compute_effective_geo("EU", ["UNKNOWN"], GEO_REGISTRY)
        self.assertEqual(result, EU.resolve(GEO_REGISTRY))

    def test_unknown_mixed_with_known(self):
        # UNKNOWN skipped
        result = compute_effective_geo("EU", ["UNKNOWN", "OECD"], GEO_REGISTRY)
        self.assertEqual(result, EU.resolve(GEO_REGISTRY))


class TestComputeStaticNodes(unittest.TestCase):
    def test_no_datasets_returns_none(self):
        self.assertIsNone(compute_static_nodes([]))

    def test_no_static_dataset_returns_none(self):
        result = compute_static_nodes(
            [
                {"nodes": ["n1", "n2"]},
                {"nodes": ["n3"]},
            ]
        )
        self.assertIsNone(result)

    def test_single_static_dataset_returns_its_nodes(self):
        result = compute_static_nodes(
            [
                {"nodes": ["n1", "n2"], "static": True},
            ]
        )
        self.assertEqual(result, {"n1", "n2"})

    def test_three_overlapping_static_datasets_returns_intersection(self):
        result = compute_static_nodes(
            [
                {"nodes": ["n1", "n2", "n3"], "static": True},
                {"nodes": ["n2", "n3", "n4"], "static": True},
                {"nodes": ["n3", "n4", "n5"], "static": True},
            ]
        )
        self.assertEqual(result, {"n3"})

    def test_two_disjoint_static_datasets_returns_empty_set(self):
        result = compute_static_nodes(
            [
                {"nodes": ["n1", "n2"], "static": True},
                {"nodes": ["n3", "n4"], "static": True},
            ]
        )
        self.assertEqual(result, set())

    def test_non_static_dataset_does_not_constrain(self):
        result = compute_static_nodes(
            [
                {"nodes": ["n1", "n2"], "static": True},
                {"nodes": ["n5"], "static": False},
            ]
        )
        self.assertEqual(result, {"n1", "n2"})

    def test_missing_nodes_key_treated_as_empty(self):
        result = compute_static_nodes([{"static": True}])
        self.assertEqual(result, set())
