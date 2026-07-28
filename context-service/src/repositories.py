from sqlalchemy.orm import Session


class ContextRepository:
    """Repository for managing Context objects in the database."""

    def __init__(self, db: Session):
        self._db: Session = db
