import threading
import time
import unittest

from sqlalchemy.orm import sessionmaker

from src.orm import Base
from src.models import IssuerAuth, IssuerAuthBase, ConflictPair
from src.database import create_engine_factory
from src.repositories import BaseRepository, IssuerAuthRepository, ConflictRepository
from src.exceptions import AlreadyExistsError, NotFoundError, WellFormednessViolation


class RepositoryTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine_factory("sqlite://")  # in-memory
        self.factory = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.db = self.factory()
        self.conflicts = ConflictRepository(self.db)
        self.issuer_auths = IssuerAuthRepository(self.db)
        Base.metadata.create_all(self.engine)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _conflict(self, a="Ford", b="Ferrari"):
        return self.conflicts.create(ConflictPair(context_a=a, context_b=b))


class TestConflictRepository(RepositoryTestCase):
    def test_create_normalizes_order(self):
        conflict = self._conflict("Ford", "Ferrari")
        self.assertEqual((conflict.context_a, conflict.context_b), ("Ferrari", "Ford"))

    def test_create_duplicate_either_order_raises(self):
        self._conflict("Ford", "Ferrari")
        with self.assertRaises(AlreadyExistsError):
            self._conflict("Ferrari", "Ford")

    def test_create_already_held_by_issuer_auth_raises(self):
        self.issuer_auths.create(IssuerAuth(name="i1", contexts=["Ford", "Ferrari"]))
        with self.assertRaises(WellFormednessViolation) as cm:
            self._conflict("Ford", "Ferrari")
        self.assertIn("i1", cm.exception.issuers)
        # Rejected conflict must not have been persisted.
        self.assertEqual(self.conflicts.get_all(), [])

    def test_exists(self):
        self.assertFalse(self.conflicts.exists("Ford", "Ferrari"))
        self._conflict("Ford", "Ferrari")
        self.assertTrue(self.conflicts.exists("Ferrari", "Ford"))

    def test_get_for_context_either_side(self):
        self._conflict("Ford", "Ferrari")
        for context in ("Ford", "Ferrari"):
            result = self.conflicts.get_for_context(context)
            self.assertEqual(
                [(c.context_a, c.context_b) for c in result], [("Ferrari", "Ford")]
            )

    def test_get_for_context_no_match(self):
        self.assertEqual(self.conflicts.get_for_context("Finance"), [])

    def test_create_batch_atomic_on_failure(self):
        self._conflict("Ford", "Ferrari")
        batch = [
            ConflictPair(context_a="BMW", context_b="Mercedes"),
            ConflictPair(context_a="Ford", context_b="Ferrari"),  # duplicate
        ]
        with self.assertRaises(AlreadyExistsError):
            self.conflicts.create_batch(batch)
        # BMW|Mercedes must not have been committed either.
        self.assertEqual(len(self.conflicts.get_all()), 1)

    def test_create_batch_checks_within_batch(self):
        batch = [
            ConflictPair(context_a="Ford", context_b="Ferrari"),
            ConflictPair(context_a="Ferrari", context_b="Ford"),  # same, swapped
        ]
        with self.assertRaises(AlreadyExistsError):
            self.conflicts.create_batch(batch)

    def test_create_batch_success(self):
        created = self.conflicts.create_batch(
            [
                ConflictPair(context_a="Ford", context_b="Ferrari"),
                ConflictPair(context_a="BMW", context_b="Mercedes"),
            ]
        )
        self.assertEqual(len(created), 2)
        self.assertEqual(len(self.conflicts.get_all()), 2)

    def test_delete_either_order(self):
        self._conflict("Ford", "Ferrari")
        self.conflicts.delete(
            ConflictPair(context_a="Ford", context_b="Ferrari")
        )  # no exception = success
        self.assertEqual(self.conflicts.get_all(), [])

    def test_delete_missing_raises(self):
        with self.assertRaises(NotFoundError):
            self.conflicts.delete(ConflictPair(context_a="Ford", context_b="Ferrari"))

    def test_delete_all(self):
        self._conflict("Ford", "Ferrari")
        self._conflict("BMW", "Mercedes")
        self.assertEqual(self.conflicts.delete_all(), 2)
        self.assertEqual(self.conflicts.get_all(), [])


class TestIssuerAuthRepository(RepositoryTestCase):
    def test_create_get(self):
        issuer_auth = IssuerAuth(name="i1", contexts=["Ford"])
        self.issuer_auths.create(issuer_auth)
        row = self.issuer_auths.get("i1")
        self.assertIsNotNone(row)
        self.assertEqual(row.model_dump(), issuer_auth.model_dump())

    def test_get_missing_returns_none(self):
        self.assertIsNone(self.issuer_auths.get("nope"))

    def test_create_duplicate_raises(self):
        issuer_auth = IssuerAuth(name="i1", contexts=["Ford"])
        self.issuer_auths.create(issuer_auth)
        with self.assertRaises(AlreadyExistsError):
            self.issuer_auths.create(issuer_auth)

    def test_create_with_conflict_raises(self):
        self._conflict("Ford", "Ferrari")
        issuer_auth = IssuerAuth(name="i1", contexts=["Ford", "Ferrari"])
        with self.assertRaises(WellFormednessViolation) as cm:
            self.issuer_auths.create(issuer_auth)
        self.assertIn(("Ferrari", "Ford"), cm.exception.conflicts)
        # Rejected creation must not leave a partial row behind.
        self.assertIsNone(self.issuer_auths.get("i1"))

    def test_create_without_conflict_succeeds(self):
        self._conflict("Ford", "Ferrari")
        issuer_auth = IssuerAuth(name="i1", contexts=["Ford", "Finance"])
        self.issuer_auths.create(issuer_auth)
        self.assertTrue(self.issuer_auths.exists("i1"))

    def test_update_introducing_conflict_raises(self):
        self._conflict("Ford", "Ferrari")
        self.issuer_auths.create(IssuerAuth(name="i1", contexts=["Ford"]))
        with self.assertRaises(WellFormednessViolation):
            self.issuer_auths.update("i1", IssuerAuthBase(contexts=["Ford", "Ferrari"]))
        # Rejected update must not have mutated the row.
        self.assertEqual(self.issuer_auths.get("i1").contexts, ["Ford"])

    def test_update_missing_returns_none(self):
        self.assertIsNone(
            self.issuer_auths.update("nope", IssuerAuthBase(contexts=["Ford"]))
        )

    def test_create_batch_atomic_on_failure(self):
        self._conflict("Ford", "Ferrari")
        batch = [
            IssuerAuth(name="i1", contexts=["Ford"]),
            IssuerAuth(name="i2", contexts=["Ford", "Ferrari"]),  # violates
        ]
        with self.assertRaises(WellFormednessViolation):
            self.issuer_auths.create_batch(batch)
        # Nothing from the batch was committed, including i1 which was
        # individually fine.
        self.assertFalse(self.issuer_auths.exists("i1"))
        self.assertFalse(self.issuer_auths.exists("i2"))

    def test_create_batch_checks_within_batch(self):
        batch = [IssuerAuth(name="i1", contexts=["Ford", "Ferrari"])]
        self._conflict("Ford", "Ferrari")
        with self.assertRaises(WellFormednessViolation):
            self.issuer_auths.create_batch(batch)

    def test_create_batch_success(self):
        created = self.issuer_auths.create_batch(
            [
                IssuerAuth(name="i1", contexts=["Ford"]),
                IssuerAuth(name="i2", contexts=[]),
            ]
        )
        self.assertEqual(len(created), 2)
        self.assertEqual(len(self.issuer_auths.get_all()), 2)

    def test_delete(self):
        self.issuer_auths.create(IssuerAuth(name="i1", contexts=[]))
        self.issuer_auths.delete("i1")  # no exception = success
        self.assertFalse(self.issuer_auths.exists("i1"))

    def test_delete_missing_raises(self):
        with self.assertRaises(NotFoundError):
            self.issuer_auths.delete("nope")

    def test_delete_all(self):
        self.issuer_auths.create(IssuerAuth(name="i1", contexts=[]))
        self.issuer_auths.create(IssuerAuth(name="i2", contexts=[]))
        self.assertEqual(self.issuer_auths.delete_all(), 2)
        self.assertEqual(self.issuer_auths.get_all(), [])
