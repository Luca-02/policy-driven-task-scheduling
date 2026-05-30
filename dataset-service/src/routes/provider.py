from typing import Annotated

from fastapi import APIRouter, Depends

from src.dependencies import get_repository
from src.database import DatasetRepository
from src.models import Item, ProviderRequest, ProviderResponse, ProviderResponseBody

router = APIRouter(tags=["provider"])

DatasetRepositoryDependency = Annotated[DatasetRepository, Depends(get_repository)]


def make_response(items: list[Item], system_error: str = "") -> ProviderResponse:
    return ProviderResponse(
        response=ProviderResponseBody(items=items, systemError=system_error)
    )


@router.post("/validate", response_model=ProviderResponse)
def validate(
    req: ProviderRequest,
    repo: DatasetRepositoryDependency,
):
    items = []

    for key in req.request.keys:
        dataset = repo.get(key)

        if dataset is None:
            items.append(
                Item(
                    key=key,
                    value="",
                    error=f"Dataset not found",
                )
            )
            continue

        items.append(
            Item(
                key=key,
                value={
                    "requirements": dataset.get("requirements", {}),
                    "sizeMB": dataset.get("sizeMB", 0),
                    "nodes": dataset.get("nodes", []),
                },
            )
        )

    return make_response(items)
