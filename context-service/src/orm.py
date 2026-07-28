from sqlalchemy import Column, String, Integer, JSON, CheckConstraint
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class IssuerORM(Base):
    __tablename__ = "issuers"

    name = Column(String(254), primary_key=True, nullable=False)
    contexts = Column(JSON, nullable=False, default=list)  # auth(i)


class ConflictORM(Base):
    __tablename__ = "context_conflicts"

    # Normalized so that context_a < context_b: this both enforces the
    # irreflexivity of X_conf (context_a == context_b is rejected by the
    # CHECK) and avoids storing the symmetric pair twice.
    context_a = Column(String(254), primary_key=True, nullable=False)
    context_b = Column(String(254), primary_key=True, nullable=False)

    __table_args__ = (
        CheckConstraint("context_a < context_b", name="ck_conflict_normalized"),
    )


class LockORM(Base):
    """
    A single sentinel row (id=1) used purely as a mutex: any write that
    must (re)verify a well-formedness invariant spanning both `issuers`
    and `context_conflicts` takes a row lock on it first, serializing
    itself against every other such write. See
    ContextRepository._acquire_lock for the rationale, and main.py for
    where the row is seeded at startup.
    """

    __tablename__ = "well_formedness_lock"

    id = Column(Integer, primary_key=True)
