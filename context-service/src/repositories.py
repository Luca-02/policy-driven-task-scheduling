from sqlalchemy import select
from sqlalchemy.orm import Session

from src.orm import IssuerORM, ConflictORM, LockORM
from src.models import Issuer, IssuerBase, Conflict, ConflictPair
from src.exceptions import AlreadyExistsError, WellFormednessViolation


class ContextRepository:
    """
    Repository for managing context-related objects (issuers and conflicts) 
    in the database.
    """

    def __init__(self, db: Session):
        self._db: Session = db

    # -------------------------------------------------------------------
    # Concurrency control
    # -------------------------------------------------------------------

    def _acquire_lock(self) -> None:
        """
        Acquires an exclusive lock over the global set of issuer
        authorizations and context conflicts, serializing any transaction
        that must (re)verify the well-formedness invariant

            (auth(i) x auth(i)) intersect X_conf = empty   for every i in I

        Without this, two concurrent transactions could each read a
        stale snapshot that looks safe in isolation (e.g. one assigns a
        new context to an issuer while the other declares that same
        context in conflict with one the issuer already holds) and both
        commit, leaving the invariant violated: a classic write-skew
        anomaly that a simple "check then write" cannot prevent.

        On PostgreSQL this takes a row lock (SELECT ... FOR UPDATE) on a
        single sentinel row, so every writer that calls this method
        serializes against every other one under default READ COMMITTED
        isolation: whichever transaction acquires the lock first runs
        its check-then-write atomically, and the next one only proceeds
        (and re-reads fresh, committed data) once the first has
        committed or rolled back.

        SQLite has no row-level locking, but every session in this
        process shares a single connection for in-memory databases (see
        create_engine_factory in database.py), which already serializes
        write transactions; the call is a no-op there. This means the
        invariant is only really exercised under concurrency on
        PostgreSQL, which is the deployment target for the prototype.
        """
        if self._db.bind.dialect.name == "sqlite":
            return
        self._db.execute(select(LockORM).with_for_update())

    @staticmethod
    def _normalize_pair(context_a: str, context_b: str) -> tuple[str, str]:
        return (
            (context_a, context_b)
            if context_a < context_b
            else (context_b, context_a)
        )

    def _conflicting_pairs(self, contexts: list[str]) -> list[tuple[str, str]]:
        """
        Returns every pair in X_conf that is fully contained in
        `contexts`, i.e. (contexts x contexts) ∩ X_conf. Must be called
        while holding the lock.
        """
        if len(contexts) < 2:
            return []

        unique = sorted(set(contexts))
        rows = (
            self._db.execute(
                select(ConflictORM).where(
                    ConflictORM.context_a.in_(unique),
                    ConflictORM.context_b.in_(unique),
                )
            )
            .scalars()
            .all()
        )
        return [(row.context_a, row.context_b) for row in rows]

    def _issuers_holding_both(self, context_a: str, context_b: str) -> list[str]:
        """
        Names of existing issuers whose auth(i) already contains both
        contexts. Must be called while holding the lock. The issuer
        table is expected to stay small (administrative data, not
        application data), so a full scan is acceptable here.
        """
        rows = self._db.execute(select(IssuerORM)).scalars().all()
        return [
            row.name
            for row in rows
            if context_a in row.contexts and context_b in row.contexts
        ]

    # -------------------------------------------------------------------
    # Issuers - auth: I -> 2^X
    # -------------------------------------------------------------------

    def get_all_issuers(self) -> list[Issuer]:
        rows = self._db.execute(select(IssuerORM)).scalars().all()
        return [Issuer.model_validate(row) for row in rows]

    def get_issuer(self, name: str) -> Issuer | None:
        row = self._db.get(IssuerORM, name)
        return Issuer.model_validate(row) if row is not None else None

    def query_issuers(self, names: list[str]) -> list[Issuer]:
        rows = (
            self._db.execute(select(IssuerORM).where(IssuerORM.name.in_(names)))
            .scalars()
            .all()
        )
        return [Issuer.model_validate(row) for row in rows]

    def exists_issuer(self, name: str) -> bool:
        return self._db.get(IssuerORM, name) is not None

    def create_issuer(self, issuer: Issuer) -> Issuer:
        self._acquire_lock()

        if self.exists_issuer(issuer.name):
            self._db.rollback()
            raise AlreadyExistsError(issuer.name)

        conflicts = self._conflicting_pairs(issuer.contexts)
        if conflicts:
            self._db.rollback()
            raise WellFormednessViolation(
                f"issuer '{issuer.name}' would hold conflicting contexts",
                conflicts=conflicts,
            )

        row = IssuerORM(**issuer.model_dump())
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return Issuer.model_validate(row)

    def create_issuers_batch(self, issuers: list[Issuer]) -> list[Issuer]:
        """
        Atomic batch creation: either every issuer is created, or none
        is (single commit at the end, single lock acquisition for the
        whole batch). An issuer later in the batch is also checked
        against the contexts assigned to issuers earlier in the same
        batch, not just against what is already committed.
        """
        self._acquire_lock()

        seen_names = set()
        rows = []
        for issuer in issuers:
            if issuer.name in seen_names or self.exists_issuer(issuer.name):
                self._db.rollback()
                raise AlreadyExistsError(issuer.name)
            seen_names.add(issuer.name)

            conflicts = self._conflicting_pairs(issuer.contexts)
            if conflicts:
                self._db.rollback()
                raise WellFormednessViolation(
                    f"issuer '{issuer.name}' would hold conflicting contexts",
                    conflicts=conflicts,
                )

            rows.append(IssuerORM(**issuer.model_dump()))

        self._db.add_all(rows)
        self._db.commit()
        for row in rows:
            self._db.refresh(row)
        return [Issuer.model_validate(row) for row in rows]

    def update_issuer(self, name: str, update: IssuerBase) -> Issuer | None:
        self._acquire_lock()

        row = self._db.get(IssuerORM, name)
        if row is None:
            self._db.rollback()
            return None

        data = update.model_dump(exclude_unset=True)
        new_contexts = data.get("contexts", row.contexts)
        conflicts = self._conflicting_pairs(new_contexts)
        if conflicts:
            self._db.rollback()
            raise WellFormednessViolation(
                f"issuer '{name}' would hold conflicting contexts",
                conflicts=conflicts,
            )

        for key, value in data.items():
            setattr(row, key, value)

        self._db.commit()
        self._db.refresh(row)
        return Issuer.model_validate(row)

    def delete_issuer(self, name: str) -> bool:
        row = self._db.get(IssuerORM, name)
        if row is None:
            return False

        self._db.delete(row)
        self._db.commit()
        return True

    def delete_all_issuers(self) -> int:
        rows = self._db.execute(select(IssuerORM)).scalars().all()
        for row in rows:
            self._db.delete(row)
        self._db.commit()
        return len(rows)

    # -------------------------------------------------------------------
    # Conflicts - X_conf ⊆ X x X (symmetric, irreflexive)
    # -------------------------------------------------------------------

    def get_all_conflicts(self) -> list[Conflict]:
        rows = self._db.execute(select(ConflictORM)).scalars().all()
        return [Conflict.model_validate(row) for row in rows]

    def create_conflict(self, pair: ConflictPair) -> Conflict:
        context_a, context_b = self._normalize_pair(pair.context_a, pair.context_b)

        self._acquire_lock()

        if self._db.get(ConflictORM, (context_a, context_b)) is not None:
            self._db.rollback()
            raise AlreadyExistsError(f"{context_a} | {context_b}")

        # Symmetric check to create_issuer/update_issuer: a new conflict
        # cannot be declared between two contexts that some existing
        # issuer already holds together, otherwise
        # (auth(i) x auth(i)) ∩ X_conf = ∅ would break retroactively for
        # that issuer.
        offending = self._issuers_holding_both(context_a, context_b)
        if offending:
            self._db.rollback()
            raise WellFormednessViolation(
                f"contexts '{context_a}' and '{context_b}' are jointly held "
                f"by {len(offending)} existing issuer(s)",
                issuers=offending,
            )

        row = ConflictORM(context_a=context_a, context_b=context_b)
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return Conflict.model_validate(row)

    def delete_conflict(self, context_a: str, context_b: str) -> bool:
        # Deleting a conflict can only relax the invariant (fewer
        # forbidden pairs), so no well-formedness re-check is needed
        # here; the lock is still taken for a consistent read-then-write.
        a, b = self._normalize_pair(context_a, context_b)

        self._acquire_lock()

        row = self._db.get(ConflictORM, (a, b))
        if row is None:
            self._db.rollback()
            return False

        self._db.delete(row)
        self._db.commit()
        return True

    def delete_all_conflicts(self) -> int:
        rows = self._db.execute(select(ConflictORM)).scalars().all()
        for row in rows:
            self._db.delete(row)
        self._db.commit()
        return len(rows)
