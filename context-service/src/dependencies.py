from fastapi import Depends, Request
from sqlalchemy.orm import Session

from src.repositories import ContextRepository


def get_session(req: Request):
    """Yields a managed SQLAlchemy session."""
    session_factory = req.app.state.session_factory
    with session_factory() as db:
        yield db


def get_repository(db: Session = Depends(get_session)) -> ContextRepository:
    return ContextRepository(db)
