import unittest

from src.geo import GeographicGroup


def make_registry(*groups: GeographicGroup) -> dict[str, GeographicGroup]:
    return {g.name: g for g in groups}


EU = GeographicGroup("EU", ["eu-north", "eu-south", "eu-east", "eu-west"], [])
US = GeographicGroup("US", ["us-north", "us-south", "us-east", "us-west"], [])
OECD = GeographicGroup("OECD", [], ["EU", "US"])
APAC = GeographicGroup("APAC", ["apac-east"], [])

REGISTRY = make_registry(EU, US, OECD, APAC)


class TestGeographicGroupResolveLeaf(unittest.TestCase):
    def test_leaf_returns_own_locations(self):
        res = EU.resolve(REGISTRY)
        self.assertIsInstance(res, set)
        self.assertEqual(res, {"eu-north", "eu-south", "eu-east", "eu-west"})

    def test_leaf_empty_registry_still_resolves(self):
        g = GeographicGroup("X", ["loc-a", "loc-b"], [])
        self.assertEqual(g.resolve({}), {"loc-a", "loc-b"})


class TestGeographicGroupResolveComposite(unittest.TestCase):
    def test_composite_union_of_includes(self):
        self.assertEqual(
            OECD.resolve(REGISTRY), EU.resolve(REGISTRY) | US.resolve(REGISTRY)
        )

    def test_composite_with_own_locations_and_includes(self):
        extended = GeographicGroup("EXT", ["extra-loc"], ["EU"])
        registry = make_registry(EU, extended)
        result = extended.resolve(registry)
        self.assertIn("extra-loc", result)
        self.assertTrue(result.issuperset(EU.resolve(REGISTRY)))

    def test_multi_level_hierarchy(self):
        world = GeographicGroup("World", [], ["OECD", "APAC"])
        registry = make_registry(EU, US, OECD, APAC, world)
        result = world.resolve(registry)
        self.assertTrue(result.issuperset(EU.resolve(REGISTRY)))
        self.assertTrue(result.issuperset(US.resolve(REGISTRY)))
        self.assertTrue(result.issuperset(APAC.resolve(REGISTRY)))

    def test_shared_dependency_not_duplicated(self):
        g1 = GeographicGroup("G1", [], ["EU"])
        g2 = GeographicGroup("G2", [], ["EU", "US"])
        top = GeographicGroup("Top", [], ["G1", "G2"])
        registry = make_registry(EU, US, g1, g2, top)
        self.assertEqual(
            top.resolve(registry), EU.resolve(REGISTRY) | US.resolve(REGISTRY)
        )


class TestGeographicGroupResolveMissing(unittest.TestCase):
    def test_missing_include_silently_ignored(self):
        g = GeographicGroup("G", ["loc-x"], ["NONEXISTENT"])
        result = g.resolve({})
        # Only own locations are returned, the missing include contributes nothing.
        self.assertEqual(result, {"loc-x"})

    def test_all_includes_missing_returns_own_locations_only(self):
        g = GeographicGroup("G", ["loc-x"], ["A", "B", "C"])
        self.assertEqual(g.resolve({}), {"loc-x"})

    def test_partial_includes_missing(self):
        g = GeographicGroup("G", [], ["EU", "MISSING"])
        result = g.resolve(make_registry(EU))
        self.assertEqual(result, EU.resolve(REGISTRY))


class TestGeographicGroupResolveCycles(unittest.TestCase):
    def test_direct_self_cycle_returns_own_locations(self):
        g = GeographicGroup("G", ["loc-x"], ["G"])
        result = g.resolve(make_registry(g))
        self.assertEqual(result, {"loc-x"})

    def test_indirect_cycle_returns_combined_locations(self):
        # A -> B -> A: both own locations should appear, no infinite recursion.
        a = GeographicGroup("A", ["loc-a"], ["B"])
        b = GeographicGroup("B", ["loc-b"], ["A"])
        registry = make_registry(a, b)
        self.assertEqual(a.resolve(registry), {"loc-a", "loc-b"})

    def test_diamond_dependency_not_a_cycle(self):
        base = GeographicGroup("Base", ["loc-x"], [])
        left = GeographicGroup("Left", [], ["Base"])
        right = GeographicGroup("Right", [], ["Base"])
        top = GeographicGroup("Top", [], ["Left", "Right"])
        registry = make_registry(base, left, right, top)
        self.assertEqual(top.resolve(registry), {"loc-x"})
