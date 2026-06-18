from typing import Annotated

from fastapi import APIRouter, Depends

from src.dependencies import get_repository
from src.database import DatasetRepository
from src.models import (
    Item,
    ProviderRequest,
    ProviderResponse,
    ProviderResponseBody,
)

router = APIRouter(tags=["provider"])

DatasetRepositoryDep = Annotated[DatasetRepository, Depends(get_repository)]


def make_response(items: list[Item], system_error: str = "") -> ProviderResponse:
    return ProviderResponse(
        response=ProviderResponseBody(items=items, systemError=system_error)
    )


@router.post("/validate", response_model=ProviderResponse)
def validate(
    req: ProviderRequest,
    repo: DatasetRepositoryDep,
):
    items = []
    for key in req.request.keys:
        dataset = repo.get(key)
        if dataset is None:
            items.append(Item(key=key, error=f"Dataset '{key}' not found"))
            continue

        value = {
            "requirements": dataset.requirements,
            "size_mb": dataset.size_mb,
            "nodes": dataset.nodes,
        }
        # geo is omitted from the response when None so that Rego can
        # distinguish not set (Omega) from an empty string.
        if dataset.geo is not None:
            value["geo"] = dataset.geo

        items.append(Item(key=key, value=value))

    return make_response(items)
