from typing import Any, Annotated

from pydantic import BaseModel, Field

from src.config import DEFAULT_GATEKEEPER_API_VERSION

# -----------------------------------------------------------------------------
# Domain models
# -----------------------------------------------------------------------------

# A property level is a non-negative integer (0 = no requirement).
Level = Annotated[int, Field(ge=0)]


class DatasetBase(BaseModel):
    """Base dataset metadata, used for both creation and update."""

    requirements: dict[str, Level] = Field(default_factory=dict)
    sizeMB: int = Field(ge=0)
    nodes: list[str] = Field(default_factory=list)


class Dataset(DatasetBase):
    """Full dataset as stored and returned by the API."""

    name: str


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
    apiVersion: str = DEFAULT_GATEKEEPER_API_VERSION
    kind: str = "ProviderResponse"
    response: ProviderResponseBody
