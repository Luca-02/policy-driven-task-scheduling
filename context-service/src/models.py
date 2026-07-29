from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

GATEKEEPER_API_VERSION = "externaldata.gatekeeper.sh/v1beta1"

# -----------------------------------------------------------------------------
# Domain models
# -----------------------------------------------------------------------------


class IssuerAuthBase(BaseModel):
    """Base issuer authorization payload, used for both creation and update."""

    contexts: list[str] = Field(default_factory=list)  # auth(i)


class IssuerAuth(IssuerAuthBase):
    """Issuer's authorization record as stored and returned by the API"""

    name: str

    model_config = ConfigDict(from_attributes=True)


class IssuerAuthQuery(BaseModel):
    keys: list[str] = Field(default_factory=list)


class ConflictPair(BaseModel):
    """
    An unordered pair of conflicting contexts, as submitted by an admin.
    Storage normalizes it so that context_a < context_b: this both
    guarantees the irreflexivity of X_conf and avoids storing the
    symmetric pair twice.
    """

    context_a: str
    context_b: str

    @model_validator(mode="after")
    def _normalize(self):
        if self.context_a == self.context_b:
            raise ValueError("a conflict pair must relate two distinct contexts")
        if self.context_a > self.context_b:
            self.context_a, self.context_b = self.context_b, self.context_a
        return self

    def __str__(self):
        return f"{self.context_a}|{self.context_b}"


class Conflict(ConflictPair):
    """A conflict pair as stored (context_a < context_b)."""

    model_config = ConfigDict(from_attributes=True)


# -----------------------------------------------------------------------------
# Gatekeeper External Data Provider protocol
# -----------------------------------------------------------------------------


class ProviderRequestBody(BaseModel):
    keys: list[str] = Field(default_factory=list)


class ProviderRequest(BaseModel):
    apiVersion: str | None = None
    kind: str | None = None
    request: ProviderRequestBody


class Item(BaseModel):
    key: str
    value: Any = ""
    error: str = ""


class ProviderResponseBody(BaseModel):
    idempotent: bool = True
    items: list[Item] = Field(default_factory=list)
    systemError: str = ""


class ProviderResponse(BaseModel):
    apiVersion: str = GATEKEEPER_API_VERSION
    kind: str = "ProviderResponse"
    response: ProviderResponseBody
