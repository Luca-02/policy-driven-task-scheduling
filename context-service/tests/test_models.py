import unittest

from pydantic import ValidationError

from src.models import ConflictPair, Conflict


class TestConflictPair(unittest.TestCase):
    def test_normalizes_order(self):
        pair = ConflictPair(context_a="Ford", context_b="Ferrari")
        self.assertEqual((pair.context_a, pair.context_b), ("Ferrari", "Ford"))

    def test_already_ordered_stays_ordered(self):
        pair = ConflictPair(context_a="Ferrari", context_b="Ford")
        self.assertEqual((pair.context_a, pair.context_b), ("Ferrari", "Ford"))

    def test_irreflexive_rejected(self):
        with self.assertRaises(ValidationError):
            ConflictPair(context_a="Ford", context_b="Ford")

    def test_str(self):
        pair = ConflictPair(context_a="Ford", context_b="Ferrari")
        self.assertEqual(str(pair), "Ferrari|Ford")

    def test_conflict_inherits_normalization_and_str(self):
        conflict = Conflict(context_a="Ford", context_b="Ferrari")
        self.assertEqual((conflict.context_a, conflict.context_b), ("Ferrari", "Ford"))
        self.assertEqual(str(conflict), "Ferrari|Ford")
