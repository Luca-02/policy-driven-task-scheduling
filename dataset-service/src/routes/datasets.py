from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from src.database import DatasetRepository
from src.dependencies import get_repository
from src.models import Dataset, DatasetBase

_RESPONSE_MODEL_KWARGS = {"response_model_exclude_none": True}

router = APIRouter(prefix="/datasets", tags=["datasets"])

DatasetRepositoryDep = Annotated[DatasetRepository, Depends(get_repository)]


@router.get("", response_model=list[Dataset], **_RESPONSE_MODEL_KWARGS)
def list_datasets(repo: DatasetRepositoryDep):
    return repo.list()


@router.get("/{name}", response_model=Dataset, **_RESPONSE_MODEL_KWARGS)
def get_dataset(name: str, repo: DatasetRepositoryDep):
    dataset = repo.get(name)
    if dataset is None:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {name}")
    return dataset


@router.post("", response_model=Dataset, status_code=201, **_RESPONSE_MODEL_KWARGS)
def create_dataset(
    dataset: Dataset,
    repo: DatasetRepositoryDep,
):
    created = repo.create(dataset)
    if created is None:
        raise HTTPException(
            status_code=409, detail=f"Dataset already exists: {dataset.name}"
        )
    return created


@router.post("/batch", response_model=list[Dataset], status_code=201, **_RESPONSE_MODEL_KWARGS)
def create_datasets(
    datasets: list[Dataset],
    repo: DatasetRepositoryDep,
):
    created = []
    for dataset in datasets:
        if repo.exists(dataset.name):
            raise HTTPException(
                status_code=409, detail=f"Dataset already exists: {dataset.name}"
            )

        created.append(repo.create(dataset))
    return created


# TODO: Add versioning suppoert for the assumption of immutability of metadata.
# This will mitigate the Time-of-check to Time-of-use race condition that can occur when updating metadata.
@router.put("/{name}", response_model=Dataset, **_RESPONSE_MODEL_KWARGS)
def update_dataset(
    name: str,
    dataset: DatasetBase,
    repo: DatasetRepositoryDep,
):
    updated = repo.update(name, dataset)
    if updated is None:
        raise HTTPException(
            status_code=404,
            detail=f"Dataset not found: {name}",
        )
    return updated


@router.delete("/{name}", status_code=204)
def delete_dataset(name: str, repo: DatasetRepositoryDep):
    if not repo.delete(name):
        raise HTTPException(
            status_code=404,
            detail=f"Dataset not found: {name}",
        )


@router.delete("", status_code=204)
def delete_all_datasets(repo: DatasetRepositoryDep):
    count = repo.delete_all()
    if count == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No datasets to delete",
        )
