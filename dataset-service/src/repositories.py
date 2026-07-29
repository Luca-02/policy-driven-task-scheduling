from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from src.orm import DatasetORM
from src.models import Dataset, DatasetBase
from src.exceptions import NotFoundError, AlreadyExistsError


class DatasetRepository:
    """Repository for managing Dataset objects in the database."""

    def __init__(self, db: Session):
        self._db: Session = db

    def get_all(self) -> list[Dataset]:
        rows = self._db.execute(select(DatasetORM)).scalars().all()
        return [Dataset.model_validate(row) for row in rows]

    def get(self, name: str) -> Dataset:
        row = self._db.get(DatasetORM, name)
        if row is None:
            raise NotFoundError(identifier=name)
        return Dataset.model_validate(row)

    def query(self, names: list[str]) -> list[Dataset]:
        rows = (
            self._db.execute(select(DatasetORM).where(DatasetORM.name.in_(names)))
            .scalars()
            .all()
        )
        return [Dataset.model_validate(row) for row in rows]

    def exists(self, name: str) -> bool:
        return self._db.get(DatasetORM, name) is not None

    def create(self, dataset: Dataset) -> Dataset:
        if self.exists(dataset.name):
            self._db.rollback()
            raise AlreadyExistsError(dataset.name)

        row = DatasetORM(**dataset.model_dump())
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return Dataset.model_validate(row)

    def update(self, name: str, update: DatasetBase) -> Dataset:
        row = self._db.get(DatasetORM, name)
        if row is None:
            self._db.rollback()
            raise NotFoundError(identifier=name)

        for key, value in update.model_dump(exclude_unset=True).items():
            setattr(row, key, value)

        self._db.commit()
        self._db.refresh(row)
        return Dataset.model_validate(row)

    def delete(self, name: str) -> None:
        row = self._db.get(DatasetORM, name)
        if row is None:
            self._db.rollback()
            raise NotFoundError(identifier=name)

        self._db.delete(row)
        self._db.commit()

    def delete_all(self) -> int:
        result = self._db.execute(delete(DatasetORM))
        self._db.commit()
        if result.rowcount == 0:
            raise NotFoundError(message="no datasets to delete")
        return result.rowcount
