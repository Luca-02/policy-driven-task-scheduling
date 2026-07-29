class ContextServiceError(Exception):
    """Base class for domain errors translated to HTTP responses by the routes."""


class NotFoundError(ContextServiceError):
    """Raised when an operation targets a resource that doesn't exist."""

    def __init__(self, identifier: str = "", message: str | None = None):
        self.identifier = identifier
        super().__init__(message or f"not found: {identifier}")


class AlreadyExistsError(ContextServiceError):
    """Raised when trying to create a resource that already exists."""

    def __init__(self, name: str):
        self.name = name
        super().__init__(f"already exists: {name}")


class WellFormednessViolation(ContextServiceError):
    """
    Raised when an operation would break one of the well-formedness
    invariants required by the formal model:

        (auth(i) x auth(i)) intersect X_conf = empty

    Two symmetric operations can violate it, and both are guarded by the
    same lock (see `BaseRepository._acquire_lock`):
      - assigning a new context to an issuer authorization that
        conflicts with one it already holds (`conflicts` is populated
        with the offending pairs);
      - declaring a new conflict between two contexts that are already
        jointly held by an existing issuer authorization (`issuers` is
        populated with the offending issuer names).
    """

    def __init__(
        self,
        message: str,
        conflicts: list[tuple[str, str]] | None = None,
        issuers: list[str] | None = None,
    ):
        self.conflicts = conflicts or []
        self.issuers = issuers or []
        super().__init__(message)

    def details(self) -> dict:
        detail = {"msg": str(self)}
        if self.conflicts:
            detail["conflicts"] = [list(pair) for pair in self.conflicts]
        if self.issuers:
            detail["issuers"] = self.issuers
        return detail
