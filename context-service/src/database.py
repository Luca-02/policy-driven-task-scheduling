from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import NullPool, StaticPool


def create_engine_factory(db_url: str) -> Engine:
    """
    Create a SQLAlchemy engine.
    - PostgreSQL: connection pooling with pre-ping.
    - SQLite (in-memory): shared across sessions via StaticPool.
    - SQLite (file): persistent, NullPool to avoid file locking issues across threads.
    """
    if db_url in ("sqlite://", "sqlite:///:memory:"):
        # In-memory SQLite database used for testing purposes
        return create_engine(
            db_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    elif db_url.startswith("sqlite"):
        # Persistent SQLite database (file-based)
        return create_engine(
            db_url,
            connect_args={"check_same_thread": False},
            poolclass=NullPool,
        )

    # PostgreSQL o altri DB
    return create_engine(db_url, pool_pre_ping=True)
