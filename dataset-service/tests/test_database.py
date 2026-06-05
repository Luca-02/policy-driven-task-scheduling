import unittest

from sqlalchemy.orm import sessionmaker

from src.orm import Base
from src.models import Dataset, DatasetBase
from src.database import DatasetRepository, create_engine_factory


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
            sizeMB=1024,
            nodes=["kind-worker2"],
        )

    def _d2(self):
        return Dataset(
            name="d2",
            requirements={"security": 1, "computation": 3},
            sizeMB=2048,
            nodes=["kind-worker3"],
        )

    def test_create_get(self):
        dataset = self._d1()
        self.repo.create(dataset)
        row = self.repo.get(dataset.name)
        self.assertIsNotNone(row)
        self.assertEqual(row.model_dump(), dataset.model_dump())

    def test_create_exists(self):
        dataset = self._d1()
        self.assertIsNotNone(self.repo.create(dataset))
        self.assertIsNone(self.repo.create(dataset))

    def test_exists(self):
        dataset = self._d1()
        self.assertFalse(self.repo.exists(dataset.name))
        self.repo.create(dataset)
        self.assertTrue(self.repo.exists(dataset.name))

    def test_list(self):
        self.repo.create(self._d1())
        self.repo.create(self._d2())
        self.assertEqual(len(self.repo.list()), 2)

    def test_update_replaces(self):
        dataset = self._d1()
        update = DatasetBase(requirements={"security": 3}, sizeMB=0, nodes=[])
        self.repo.create(dataset)
        self.repo.update(dataset.name, update)
        row = self.repo.get(dataset.name)
        for key, value in update.model_dump(exclude_unset=True).items():
            self.assertEqual(getattr(row, key), value)

    def test_update_missing_dataset(self):
        self.assertIsNone(
            self.repo.update("nope", DatasetBase(requirements={}, sizeMB=0, nodes=[]))
        )

    def test_delete(self):
        dataset = self._d1()
        self.repo.create(dataset)
        self.assertTrue(self.repo.delete(dataset.name))
        self.assertFalse(self.repo.exists(dataset.name))

    def test_delete_missing_false(self):
        self.assertFalse(self.repo.delete("nope"))

    def test_delete_all(self):
        self.repo.create(self._d1())
        self.repo.create(self._d2())
        count = self.repo.delete_all()
        self.assertEqual(count, 2)
        self.assertEqual(len(self.repo.list()), 0)
