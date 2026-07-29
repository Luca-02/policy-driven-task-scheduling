from fastapi import Depends, Request
from sqlalchemy.orm import Session

from src.config import Config
from src.repositories import DatasetRepository


def get_session(req: Request):
    """Yields a managed SQLAlchemy session."""
    session_factory = req.app.state.session_factory
    with session_factory() as db:
        yield db


def get_config(req: Request) -> Config:
    return req.app.state.config


def get_dataset_repository(
    db: Session = Depends(get_session),
) -> DatasetRepository:
    return DatasetRepository(db)
