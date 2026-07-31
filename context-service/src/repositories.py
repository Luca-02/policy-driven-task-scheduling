from sqlalchemy import select, or_, and_
from sqlalchemy.orm import Session

from src.orm import IssuerAuthORM, ConflictORM, LockORM
from src.models import IssuerAuth, IssuerAuthBase, Conflict, ConflictPair
from src.exceptions import AlreadyExistsError, NotFoundError, WellFormednessViolation


class BaseRepository:
    """
    Common base for IssuerAuthRepository and ConflictRepository: holds
    the db session, plus the concurrency-control helper both need
    because they must jointly enforce a single invariant that spans
    both of their tables:

        (auth(i) x auth(i)) intersect X_conf = empty
    """

    def __init__(self, db: Session):
        self._db: Session = db

    def _acquire_lock(self) -> None:
        """
        Acquires an exclusive lock over the global set of issuer authorizations and
        context conflicts, serializing any transaction that must (re)verify the invariant:

            (auth(i) x auth(i)) intersect X_conf = empty

        Both write paths touch it (assigning a context to an issuer authorization, in
        `IssuerAuthRepository`; declaring a new conflict, in `ConflictRepository`), so
        a "check then write" inside just one of them cannot prevent write skew between the
        two: calling this before either write path serializes them against each other, not
        just against themselves.

        On PostgreSQL this takes a row lock (SELECT ... FOR UPDATE) on a single sentinel
        row, so every writer that calls this method serializes against every other one under
        default READ COMMITTED isolation: whichever transaction acquires the lock first runs
        its check-then-write atomically, and the next one only proceeds (and re-reads fresh,
        committed data) once the first has committed or rolled back.

        SQLite has no row-level locking, but every session in this process shares a single
        connection for in-memory databases (see create_engine_factory in `database.py`), which
        already serializes write transactions; the call is a no-op there. This means the
        invariant is only really exercised under concurrency on PostgreSQL, which is the
        deployment target for the prototype.
        """
        if self._db.bind.dialect.name == "sqlite":
            return
        self._db.execute(select(LockORM).with_for_update())


class ConflictRepository(BaseRepository):
    """Repository for managing context conflicts."""

    def _issuers_holding_both(self, context_a: str, context_b: str) -> list[str]:
        """
        Names of existing issuers whose auth(i) already contains both contexts.

        Read-only access to issuers. Must be called while holding the lock (_acquire_lock).
        """
        rows = self._db.execute(select(IssuerAuthORM)).scalars().all()
        return [
            row.name
            for row in rows
            if context_a in row.contexts and context_b in row.contexts
        ]

    def get_all(self) -> list[Conflict]:
        rows = self._db.execute(select(ConflictORM)).scalars().all()
        return [Conflict.model_validate(row) for row in rows]

    def get(self, context: str) -> list[Conflict]:
        rows = (
            self._db.execute(
                select(ConflictORM).where(
                    or_(
                        ConflictORM.context_a == context,
                        ConflictORM.context_b == context,
                    )
                )
            )
            .scalars()
            .all()
        )
        return [Conflict.model_validate(row) for row in rows]

    def exists(self, context_a: str, context_b: str) -> bool:
        try:
            pair = ConflictPair(context_a=context_a, context_b=context_b)
        except ValueError:
            return False
        return self._db.get(ConflictORM, (pair.context_a, pair.context_b)) is not None

    def create(self, pair: ConflictPair) -> Conflict:
        self._acquire_lock()

        if self.exists(pair.context_a, pair.context_b):
            self._db.rollback()
            raise AlreadyExistsError(str(pair))

        # Symmetric check to IssuerRepository.create/update: a new
        # conflict cannot be declared between two contexts that some
        # existing issuer already holds together, otherwise:
        #
        #   (auth(i) x auth(i)) intersect X_conf = not empty
        #
        # would break retroactively for that issuer
        offending = self._issuers_holding_both(pair.context_a, pair.context_b)
        if offending:
            self._db.rollback()
            raise WellFormednessViolation(
                f"contexts {pair.context_a!r} and {pair.context_b!r} are jointly held "
                f"by {len(offending)} existing issuer authorization(s)",
                issuers=offending,
            )

        row = ConflictORM(context_a=pair.context_a, context_b=pair.context_b)
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return Conflict.model_validate(row)

    def create_batch(self, pairs: list[ConflictPair]) -> list[Conflict]:
        """
        Atomic batch creation: either every pair is created, or none is (single commit
        at the end, single lock acquisition for the whole batch). A pair later in the
        batch is also checked against pairs earlier in the same batch, not just against
        what is already committed.
        """
        self._acquire_lock()

        seen_pairs = set()
        rows = []
        for pair in pairs:
            key = (pair.context_a, pair.context_b)

            if key in seen_pairs or self.exists(pair.context_a, pair.context_b):
                self._db.rollback()
                raise AlreadyExistsError(str(pair))
            seen_pairs.add(key)

            offending = self._issuers_holding_both(pair.context_a, pair.context_b)
            if offending:
                self._db.rollback()
                raise WellFormednessViolation(
                    f"contexts {pair.context_a!r} and {pair.context_b!r} are jointly "
                    f"held by {len(offending)} existing issuer authorization(s)",
                    issuers=offending,
                )

            rows.append(ConflictORM(context_a=pair.context_a, context_b=pair.context_b))

        self._db.add_all(rows)
        self._db.commit()
        for row in rows:
            self._db.refresh(row)
        return [Conflict.model_validate(row) for row in rows]

    def delete(self, pair: ConflictPair) -> None:
        # Deleting a conflict can only relax the invariant, so no
        # well-formedness re-check is needed here.
        self._acquire_lock()

        row = self._db.get(ConflictORM, (pair.context_a, pair.context_b))
        if row is None:
            self._db.rollback()
            raise NotFoundError(str(pair))

        self._db.delete(row)
        self._db.commit()

    def delete_all(self) -> int:
        rows = self._db.execute(select(ConflictORM)).scalars().all()
        for row in rows:
            self._db.delete(row)
        self._db.commit()
        return len(rows)


class IssuerAuthRepository(BaseRepository):
    """Repository for managing issuer authorizations (auth: I -> 2^X)."""

    def _conflicting_pairs(self, contexts: list[str]) -> list[tuple[str, str]]:
        """
        Returns every pair in X_conf that is fully contained in `contexts`:

            (contexts x contexts) intersect X_conf

        Read-only access to context_conflicts. Must be called while holding
        the lock (_acquire_lock).
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

    def _cross_conflicting_pairs(
        self,
        set_a: list[str],
        set_b: list[str],
    ) -> list[tuple[str, str]]:
        """
        Returns every pair in X_conf with one side in `set_a` and the other in `set_b`:

            (set_a x set_b) intersect X_conf
         
        Unlike `_conflicting_pairs`, this checks two distinct sets against each other 
        rather than a single set against itself, so it also matches pairs that only 
        conflict across the two sets (a context can appear in both without that alone 
        being a conflict).
        """
        if not set_a or not set_b:
            return []

        unique_a = sorted(set(set_a))
        unique_b = sorted(set(set_b))
        rows = (
            self._db.execute(
                select(ConflictORM).where(
                    or_(
                        and_(
                            ConflictORM.context_a.in_(unique_a),
                            ConflictORM.context_b.in_(unique_b),
                        ),
                        and_(
                            ConflictORM.context_a.in_(unique_b),
                            ConflictORM.context_b.in_(unique_a),
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )
        return [(row.context_a, row.context_b) for row in rows]

    def get_all(self) -> list[IssuerAuth]:
        rows = self._db.execute(select(IssuerAuthORM)).scalars().all()
        return [IssuerAuth.model_validate(row) for row in rows]

    def get(self, name: str) -> IssuerAuth | None:
        row = self._db.get(IssuerAuthORM, name)
        return IssuerAuth.model_validate(row) if row is not None else None

    def query(self, names: list[str]) -> list[IssuerAuth]:
        rows = (
            self._db.execute(select(IssuerAuthORM).where(IssuerAuthORM.name.in_(names)))
            .scalars()
            .all()
        )
        return [IssuerAuth.model_validate(row) for row in rows]

    def exists(self, name: str) -> bool:
        return self._db.get(IssuerAuthORM, name) is not None

    def wall_conflicts(self, name: str, contexts: list[str]) -> list[Conflict] | None:
        """
        Checks `(auth(i) x contexts) intersect X_conf` for the issuer `name`
        against an arbitrary set `contexts`.
        """
        issuer_auth = self.get(name)
        if issuer_auth is None:
            raise NotFoundError(name)

        pairs = self._cross_conflicting_pairs(issuer_auth.contexts, contexts)
        return [Conflict(context_a=a, context_b=b) for a, b in pairs]

    def create(self, issuer_auth: IssuerAuth) -> IssuerAuth:
        self._acquire_lock()

        if self.exists(issuer_auth.name):
            self._db.rollback()
            raise AlreadyExistsError(issuer_auth.name)

        conflicts = self._conflicting_pairs(issuer_auth.contexts)
        if conflicts:
            self._db.rollback()
            raise WellFormednessViolation(
                f"issuer {issuer_auth.name!r} would hold conflicting contexts",
                conflicts=conflicts,
            )

        row = IssuerAuthORM(**issuer_auth.model_dump())
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return IssuerAuth.model_validate(row)

    def create_batch(self, issuer_auths: list[IssuerAuth]) -> list[IssuerAuth]:
        self._acquire_lock()

        seen_names = set()
        rows = []
        for issuer_auth in issuer_auths:
            if issuer_auth.name in seen_names or self.exists(issuer_auth.name):
                self._db.rollback()
                raise AlreadyExistsError(issuer_auth.name)
            seen_names.add(issuer_auth.name)

            conflicts = self._conflicting_pairs(issuer_auth.contexts)
            if conflicts:
                self._db.rollback()
                raise WellFormednessViolation(
                    f"issuer {issuer_auth.name!r} would hold conflicting contexts",
                    conflicts=conflicts,
                )

            rows.append(IssuerAuthORM(**issuer_auth.model_dump()))

        self._db.add_all(rows)
        self._db.commit()
        for row in rows:
            self._db.refresh(row)
        return [IssuerAuth.model_validate(row) for row in rows]

    def update(self, name: str, update: IssuerAuthBase) -> IssuerAuth | None:
        self._acquire_lock()

        row = self._db.get(IssuerAuthORM, name)
        if row is None:
            self._db.rollback()
            return None

        data = update.model_dump(exclude_unset=True)
        new_contexts = data.get("contexts", row.contexts)
        conflicts = self._conflicting_pairs(new_contexts)
        if conflicts:
            self._db.rollback()
            raise WellFormednessViolation(
                f"issuer {name!r} would hold conflicting contexts",
                conflicts=conflicts,
            )

        for key, value in data.items():
            setattr(row, key, value)

        self._db.commit()
        self._db.refresh(row)
        return IssuerAuth.model_validate(row)

    def delete(self, name: str) -> None:
        row = self._db.get(IssuerAuthORM, name)
        if row is None:
            self._db.rollback()
            raise NotFoundError(name)

        self._db.delete(row)
        self._db.commit()

    def delete_all(self) -> int:
        rows = self._db.execute(select(IssuerAuthORM)).scalars().all()
        for row in rows:
            self._db.delete(row)
        self._db.commit()
        return len(rows)
