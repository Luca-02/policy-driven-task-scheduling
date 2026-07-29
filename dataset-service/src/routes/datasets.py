from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from src.config import Config
from src.dependencies import get_dataset_repository
from src.repositories import DatasetRepository
from src.models import Dataset, DatasetBase, DatasetQuery
from src.exceptions import NotFoundError, AlreadyExistsError

_RESPONSE_MODEL_KWARGS = {"response_model_exclude_none": True}

cfg = Config.from_env()
router = APIRouter(prefix="/datasets", tags=["datasets"])

DatasetRepositoryDep = Annotated[DatasetRepository, Depends(get_dataset_repository)]


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
    "/batch", response_model=list[Dataset], status_code=201, **_RESPONSE_MODEL_KWARGS
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

if cfg.debug_mode:
    @router.put("/{name}", response_model=Dataset, **_RESPONSE_MODEL_KWARGS)
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
