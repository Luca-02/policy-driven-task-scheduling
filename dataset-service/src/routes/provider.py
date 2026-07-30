from typing import Annotated

from fastapi import APIRouter, Depends

from src.dependencies import get_dataset_repository
from src.repositories import DatasetRepository
from src.models import (
    Item,
    ProviderRequest,
    ProviderResponse,
    ProviderResponseBody,
)

router = APIRouter(tags=["provider"])

DatasetRepositoryDep = Annotated[DatasetRepository, Depends(get_dataset_repository)]


def make_response(items: list[Item], system_error: str = "") -> ProviderResponse:
    return ProviderResponse(
        response=ProviderResponseBody(items=items, systemError=system_error)
    )


@router.post("/validate", response_model=ProviderResponse)
def validate(
    req: ProviderRequest,
    repo: DatasetRepositoryDep,
):
    """Resolves dataset existence and metadata for OPA Gatekeeper."""
    items = []
    datasets = repo.query(req.request.keys)
    datasets_dict = {dataset.name: dataset for dataset in datasets}

    for key in req.request.keys:
        dataset = datasets_dict.get(key)
        if dataset is None:
            items.append(Item(key=key, error=f"Dataset {key!r} not found"))
            continue

        items.append(
            Item(
                key=key,
                value=dataset.model_dump(exclude_none=True),
            )
        )

    return make_response(items)
