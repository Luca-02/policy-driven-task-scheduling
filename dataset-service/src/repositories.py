from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from src.orm import DatasetORM
from src.models import Dataset, DatasetBase


class DatasetRepository:
    """Repository for managing Dataset objects in the database."""

    def __init__(self, db: Session):
        self._db: Session = db

    def get_all(self) -> list[Dataset]:
        rows = self._db.execute(select(DatasetORM)).scalars().all()
        return [Dataset.model_validate(row) for row in rows]

    def get(self, name: str) -> Dataset | None:
        row = self._db.get(DatasetORM, name)
        return Dataset.model_validate(row) if row is not None else None

    def query(self, names: list[str]) -> list[Dataset]:
        rows = (
            self._db.execute(select(DatasetORM).where(DatasetORM.name.in_(names)))
            .scalars()
            .all()
        )
        return [Dataset.model_validate(row) for row in rows]

    def exists(self, name: str) -> bool:
        return self.get(name) is not None

    def create(self, dataset: Dataset):
        if self.exists(dataset.name):
            return None

        row = DatasetORM(**dataset.model_dump())
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return Dataset.model_validate(row)

    def update(self, name: str, update: DatasetBase) -> Dataset | None:
        row = self._db.get(DatasetORM, name)
        if row is None:
            return None

        for key, value in update.model_dump(exclude_unset=True).items():
            setattr(row, key, value)

        self._db.commit()
        self._db.refresh(row)
        return Dataset.model_validate(row)

    def delete(self, name: str) -> bool:
        row = self._db.get(DatasetORM, name)
        if row is None:
            return False

        self._db.delete(row)
        self._db.commit()
        return True

    def delete_all(self) -> int:
        stmt = delete(DatasetORM)
        result = self._db.execute(stmt)
        self._db.commit()
        return result.rowcount
