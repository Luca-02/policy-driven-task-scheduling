from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from src.config import Config
from src.dependencies import get_config, get_dataset_repository
from src.repositories import DatasetRepository
from src.models import (
    Item,
    Dataset,
    DatasetBase,
    DatasetQuery,
    ProviderRequest,
    ProviderResponse,
    ProviderResponseBody,
)
from src.exceptions import NotFoundError, AlreadyExistsError

_RESPONSE_MODEL_KWARGS = {"response_model_exclude_none": True}

router = APIRouter(prefix="/datasets", tags=["datasets"])

DatasetRepositoryDep = Annotated[DatasetRepository, Depends(get_dataset_repository)]


def verify_debug_mode(config: Annotated[Config, Depends(get_config)]):
    """
    Verify that the application is running in debug mode.
    If not, raise an HTTPException with a 404 status code
    and a message indicating that the endpoint is not available.
    """
    if not config.debug_mode:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Endpoint not available.",
        )


@router.get("", response_model=list[Dataset], **_RESPONSE_MODEL_KWARGS)
def get_all_datasets(repo: DatasetRepositoryDep):
    return repo.get_all()


@router.get("/{name}", response_model=Dataset, **_RESPONSE_MODEL_KWARGS)
def get_dataset(name: str, repo: DatasetRepositoryDep):
    try:
        return repo.get(name)
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {name}")


@router.post("/query", response_model=list[Dataset], **_RESPONSE_MODEL_KWARGS)
def query_datasets(query: DatasetQuery, repo: DatasetRepositoryDep):
    result = repo.query(query.keys)
    if len(result) != len(query.keys):
        found_keys = {dataset.name for dataset in result}
        missing_keys = set(query.keys) - found_keys
        raise HTTPException(
            status_code=404,
            detail=f"Datasets not found: {', '.join(missing_keys)}",
        )
    return result


@router.post("", response_model=Dataset, status_code=201, **_RESPONSE_MODEL_KWARGS)
def create_dataset(
    dataset: Dataset,
    repo: DatasetRepositoryDep,
):
    try:
        return repo.create(dataset)
    except AlreadyExistsError:
        raise HTTPException(
            status_code=409, detail=f"Dataset already exists: {dataset.name}"
        )


@router.post(
    "/batch",
    response_model=list[Dataset],
    status_code=201,
    **_RESPONSE_MODEL_KWARGS,
)
def create_datasets_batch(
    datasets: list[Dataset],
    repo: DatasetRepositoryDep,
):
    created = []
    for dataset in datasets:
        try:
            created.append(repo.create(dataset))
        except AlreadyExistsError:
            raise HTTPException(
                status_code=409, detail=f"Dataset already exists: {dataset.name}"
            )
    return created


@router.put(
    "/{name}",
    response_model=Dataset,
    dependencies=[Depends(verify_debug_mode)],
    **_RESPONSE_MODEL_KWARGS,
)
def update_dataset(
    name: str,
    dataset: DatasetBase,
    repo: DatasetRepositoryDep,
):
    """
    Debug-only endpoints. It ensure that the assumption of immutability of
    metadata is respected. These endpoints are not meant to be used in production,
    but only for testing and debugging purposes.

    This will mitigate the `Time-of-check to Time-of-use` race condition that can occur
    when updating metadata.
    """
    try:
        return repo.update(name, dataset)
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {name}")


@router.delete("/{name}", status_code=204)
def delete_dataset(name: str, repo: DatasetRepositoryDep):
    try:
        repo.delete(name)
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {name}")


@router.delete("", status_code=204)
def delete_all_datasets(repo: DatasetRepositoryDep):
    try:
        repo.delete_all()
    except NotFoundError:
        raise HTTPException(status_code=404, detail="No datasets to delete")


@router.post("/validate", response_model=ProviderResponse)
def validate(req: ProviderRequest, repo: DatasetRepositoryDep):
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

    return ProviderResponse(response=ProviderResponseBody(items=items, systemError=""))
