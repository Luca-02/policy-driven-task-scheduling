class DatasetServiceError(Exception):
    """Base class for domain errors translated to HTTP responses by the routes."""


class NotFoundError(DatasetServiceError):
    """
    Raised when an operation targets a resource that doesn't exist.
    """

    def __init__(self, identifier: str = "", message: str | None = None):
        self.identifier = identifier
        super().__init__(message or f"not found: {identifier}")


class AlreadyExistsError(DatasetServiceError):
    """Raised when trying to create a resource that already exists."""

    def __init__(self, name: str):
        self.name = name
        super().__init__(f"already exists: {name}")
