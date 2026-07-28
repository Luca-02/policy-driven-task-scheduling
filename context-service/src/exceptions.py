class ContextServiceError(Exception):
    """Base class for domain errors translated to HTTP responses by the routes."""


class AlreadyExistsError(ContextServiceError):
    """Raised when trying to create a resource that already exists."""

    def __init__(self, name: str):
        self.name = name
        super().__init__(f"already exists: {name}")


class WellFormednessViolation(ContextServiceError):
    """
    Raised when an operation would break one of the well-formedness
    invariants required by the formal model (Capitolo 3):

        (auth(i) x auth(i)) ∩ X_conf = ∅   for every i in I

    Two symmetric operations can violate it, and both are guarded by the
    same lock (see ContextRepository._acquire_lock):
      - assigning a new context to an issuer that conflicts with one it
        already holds (`conflicts` is populated with the offending pairs);
      - declaring a new conflict between two contexts that are already
        jointly held by an existing issuer (`issuers` is populated with
        the offending issuer names).
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
