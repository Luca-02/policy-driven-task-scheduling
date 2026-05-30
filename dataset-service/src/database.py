import json
import os

from tinydb import Query, TinyDB


class DatasetRepository:
    """
    Persistence layer backed by TinyDB.

    TinyDB stores all data in a single JSON file, which is human-readable
    and trivially editable for tests and demos.
    CRUD operations are persisted on write; the file can also be
    inspected/edited directly.
    """

    def __init__(self, db_path: str):
        directory = os.path.dirname(db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self._db = TinyDB(db_path)
        self._table = self._db.table("datasets")
        self._q = Query()

    def list(self) -> list[dict]:
        return self._table.all()

    def get(self, name: str) -> dict | None:
        return self._table.get(self._q.name == name)

    def exists(self, name: str) -> bool:
        return self._table.contains(self._q.name == name)

    def create(self, dataset: dict) -> dict:
        self._table.insert(dataset)
        return dataset

    def update(self, name: str, data: dict) -> dict | None:
        """Full replace of the metadata. Returns None if absent."""
        if not self.exists(name):
            return None
        record = {**data, "name": name}
        self._table.update(record, self._q.name == name)
        return self.get(name)

    def delete(self, name: str) -> bool:
        if not self.exists(name):
            return False
        self._table.remove(self._q.name == name)
        return True

    def seed_if_empty(self, seed_path: str, logger=None):
        """Load seed data only when the table is empty and the seed file exists."""
        if len(self._table) > 0:
            return
        if not seed_path or not os.path.exists(seed_path):
            return
        with open(seed_path) as f:
            data = json.load(f)
        for dataset in data.get("datasets", []):
            self._table.insert(dataset)
        if logger:
            logger.info(
                f"Seeded {len(data.get('datasets', []))} datasets from {seed_path}"
            )
