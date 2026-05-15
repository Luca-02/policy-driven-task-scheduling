import unittest

from src.models import Clause, Condition, Level, Node, Property

# --------------------------------------------------
# Thesis example testing
# --------------------------------------------------

THESIS_SECURITY = Property(name="security", levels=[
    Level(level=1, clauses=[
        Clause([Condition("cert", "Eq", ["certC"])]),
    ]),
    Level(level=2, clauses=[
        Clause([Condition("cert", "Eq", ["certB"])]),
        Clause([Condition("isolation", "Eq", ["strict"])]),
    ]),
    Level(level=3, clauses=[
        Clause([
            Condition("cert", "In", ["certA", "certB"]),
            Condition("isolation", "Eq", ["strict"]),
        ]),
    ]),
])

THESIS_COMPUTATION = Property(name="computation", levels=[
    Level(level=1, clauses=[
        Clause([Condition("cpu", "Gte", ["4"])]),
    ]),
    Level(level=2, clauses=[
        Clause([Condition("gpu", "Eq", ["t4"])]),
        Clause([Condition("cpu", "Gte", ["8"])]),
    ]),
    Level(level=3, clauses=[
        Clause([
            Condition("gpu", "In", ["a100", "h100"]),
            Condition("cpu", "Gte", ["16"]),
        ]),
    ]),
])

NODES = [
    Node("n1", {"cert": "certA", "isolation": "strict", "gpu": "a100", "cpu": "16"}),
    Node("n2", {"cert": "certB", "isolation": "standard", "gpu": "t4", "cpu": "8"}),
    Node("n3", {"cert": "certC", "isolation": "standard", "cpu": "4"}),
    Node("n4", {"cert": "certC", "isolation": "strict", "gpu": "a100", "cpu": "24"}),
    Node("n5", {"cert": "certA", "isolation": "strict", "cpu": "4"}),
]


class TestThesisExample(unittest.TestCase):
    def setUp(self):
        self.security = THESIS_SECURITY
        self.computation = THESIS_COMPUTATION
        self.nodes = {n.name: n for n in NODES}

    def _check(self, node_name, expected_security, expected_computation):
        node = self.nodes[node_name]
        self.assertEqual(node.evaluate_property(self.security), expected_security)
        self.assertEqual(node.evaluate_property(self.computation), expected_computation)

    def test_n1(self): self._check("n1", 3, 3)
    def test_n2(self): self._check("n2", 2, 2)
    def test_n3(self): self._check("n3", 1, 1)
    def test_n4(self): self._check("n4", 2, 3)
    def test_n5(self): self._check("n5", 3, 1)


# --------------------------------------------------
# Models testing
# --------------------------------------------------

class TestCondition(unittest.TestCase): 
    def test_eq(self):
        c = Condition("cert", "Eq", ["certA"])
        self.assertTrue(c.evaluate({"cert": "certA"}))
        self.assertFalse(c.evaluate({"cert": "certB"}))
 
    def test_not_eq(self):
        c = Condition("cert", "NotEq", ["certA"])
        self.assertTrue(c.evaluate({"cert": "certB"}))
        self.assertFalse(c.evaluate({"cert": "certA"}))
 
    def test_in(self):
        c = Condition("cert", "In", ["certA", "certB"])
        self.assertTrue(c.evaluate({"cert": "certA"}))
        self.assertTrue(c.evaluate({"cert": "certB"}))
        self.assertFalse(c.evaluate({"cert": "certC"}))
 
    def test_not_in(self):
        c = Condition("cert", "NotIn", ["certA", "certB"])
        self.assertTrue(c.evaluate({"cert": "certC"}))
        self.assertFalse(c.evaluate({"cert": "certA"}))
 
    def test_gt(self):
        c = Condition("cpu", "Gt", ["8"])
        self.assertTrue(c.evaluate({"cpu": "9"}))
        self.assertFalse(c.evaluate({"cpu": "8"}))
 
    def test_lt(self):
        c = Condition("cpu", "Lt", ["8"])
        self.assertTrue(c.evaluate({"cpu": "4"}))
        self.assertFalse(c.evaluate({"cpu": "8"}))
 
    def test_gte(self):
        c = Condition("cpu", "Gte", ["8"])
        self.assertTrue(c.evaluate({"cpu": "8"}))
        self.assertTrue(c.evaluate({"cpu": "16"}))
        self.assertFalse(c.evaluate({"cpu": "4"}))
 
    def test_lte(self):
        c = Condition("cpu", "Lte", ["8"])
        self.assertTrue(c.evaluate({"cpu": "8"}))
        self.assertTrue(c.evaluate({"cpu": "4"}))
        self.assertFalse(c.evaluate({"cpu": "16"}))
 
    def test_exists(self):
        c = Condition("gpu", "Exists")
        self.assertTrue(c.evaluate({"gpu": "a100"}))
        self.assertFalse(c.evaluate({"cpu": "8"}))
 
    def test_not_exists(self):
        c = Condition("gpu", "NotExists")
        self.assertTrue(c.evaluate({"cpu": "8"}))
        self.assertFalse(c.evaluate({"gpu": "a100"}))
 
    def test_missing_attribute_returns_false(self):
        c = Condition("gpu", "Eq", ["a100"])
        self.assertFalse(c.evaluate({"cpu": "8"}))
 
    def test_unknown_operator_raises(self):
        with self.assertRaises(ValueError):
            Condition("cpu", "Invalid", ["8"])
 
    def test_numeric_operator_non_integer_raises(self):
        c = Condition("cpu", "Gt", ["8"])
        with self.assertRaises(ValueError):
            c.evaluate({"cpu": "notanumber"})


class TestClause(unittest.TestCase):
    def test_all_true(self):
        clause = Clause([
            Condition("cert", "Eq", ["certA"]),
            Condition("isolation", "Eq", ["strict"]),
        ])
        self.assertTrue(clause.evaluate({"cert": "certA", "isolation": "strict"}))
 
    def test_one_false(self):
        clause = Clause([
            Condition("cert", "Eq", ["certA"]),
            Condition("isolation", "Eq", ["strict"]),
        ])
        self.assertFalse(clause.evaluate({"cert": "certA", "isolation": "standard"}))


class TestLevel(unittest.TestCase):
    def test_one_clause_satisfied(self):
        level = Level(level=2, clauses=[
            Clause([Condition("cert", "Eq", ["certB"])]),
            Clause([Condition("isolation", "Eq", ["strict"])]),
        ])
        self.assertTrue(level.evaluate({"cert": "certC", "isolation": "strict"}))

    def test_no_clause_satisfied(self):
        level = Level(level=2, clauses=[
            Clause([Condition("cert", "Eq", ["certB"])]),
            Clause([Condition("isolation", "Eq", ["strict"])]),
        ])
        self.assertFalse(level.evaluate({"cert": "certC", "isolation": "standard"}))


class TestProperty(unittest.TestCase):
    def test_implicit_level_zero(self):
        prop = Property(name="test", levels=[
            Level(level=1, clauses=[
                Clause([Condition("cert", "Eq", ["certC"])]),
            ]),
            Level(level=2, clauses=[
                Clause([Condition("cert", "Eq", ["certB"])]),
                Clause([Condition("isolation", "Eq", ["strict"])]),
            ])
        ])
        self.assertEqual(prop.max_level({"cert": "certA"}), 0)

    def test_max_level_not_first_satisfied(self):
        # n4: security should be 2, not 1
        security = THESIS_SECURITY
        attrs = {"cert": "certC", "isolation": "strict", "gpu": "a100", "cpu": "24"}
        self.assertEqual(security.max_level(attrs), 2)
