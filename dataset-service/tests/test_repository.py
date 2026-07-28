import unittest

from sqlalchemy.orm import sessionmaker

from src.orm import Base
from src.models import Dataset, DatasetBase
from src.database import create_engine_factory
from src.repositories import DatasetRepository
from src.exceptions import NotFoundError, AlreadyExistsError


class TestRepository(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine_factory("sqlite://")  # in-memory
        self.factory = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.db = self.factory()
        self.repo = DatasetRepository(self.db)
        Base.metadata.create_all(self.engine)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _d1(self):
        return Dataset(
            name="d1",
            requirements={"security": 2, "computation": 1},
            size_mb=1024,
            nodes=["kind-worker2"],
            geo="us",
            static=False,
            contexts=["personal-data"],
        )

    def _d2(self):
        return Dataset(
            name="d2",
            requirements={"security": 1, "computation": 3},
            size_mb=2048,
            nodes=["kind-worker3"],
            static=True,
        )

    def test_create_get(self):
        dataset = self._d1()
        self.repo.create(dataset)
        row = self.repo.get(dataset.name)
        self.assertEqual(row.model_dump(), dataset.model_dump())

    def test_get_missing_raises(self):
        with self.assertRaises(NotFoundError):
            self.repo.get("nope")

    def test_create_exists_raises(self):
        dataset = self._d1()
        self.repo.create(dataset)
        with self.assertRaises(AlreadyExistsError):
            self.repo.create(dataset)

    def test_query(self):
        d1 = self._d1()
        d2 = self._d2()
        self.repo.create(d1)
        self.repo.create(d2)
        rows = self.repo.query([d1.name, d2.name])
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertIn(row.model_dump(), [d1.model_dump(), d2.model_dump()])

    def test_query_partial_match_does_not_raise(self):
        self.repo.create(self._d1())
        rows = self.repo.query(["d1", "nope"])
        self.assertEqual([row.name for row in rows], ["d1"])

    def test_exists(self):
        dataset = self._d1()
        self.assertFalse(self.repo.exists(dataset.name))
        self.repo.create(dataset)
        self.assertTrue(self.repo.exists(dataset.name))

    def test_list(self):
        self.repo.create(self._d1())
        self.repo.create(self._d2())
        self.assertEqual(len(self.repo.get_all()), 2)

    def test_update_replaces(self):
        dataset = self._d1()
        update = DatasetBase(
            requirements={"security": 3},
            size_mb=0,
            nodes=[],
            geo="AS",
        )
        self.repo.create(dataset)
        self.repo.update(dataset.name, update)
        row = self.repo.get(dataset.name)
        for key, value in update.model_dump(exclude_unset=True).items():
            self.assertEqual(getattr(row, key), value)

    def test_update_missing_raises(self):
        with self.assertRaises(NotFoundError):
            self.repo.update(
                "nope",
                DatasetBase(requirements={}, size_mb=0, nodes=[], geo="AS"),
            )

    def test_delete(self):
        dataset = self._d1()
        self.repo.create(dataset)
        self.repo.delete(dataset.name)  # no exception = success
        self.assertFalse(self.repo.exists(dataset.name))

    def test_delete_missing_raises(self):
        with self.assertRaises(NotFoundError):
            self.repo.delete("nope")

    def test_delete_all(self):
        self.repo.create(self._d1())
        self.repo.create(self._d2())
        count = self.repo.delete_all()
        self.assertEqual(count, 2)
        self.assertEqual(len(self.repo.get_all()), 0)

    def test_delete_all_empty_raises(self):
        with self.assertRaises(NotFoundError):
            self.repo.delete_all()
