from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from src.database import DatasetRepository
from src.dependencies import get_repository
from src.models import DatasetBase, Dataset

router = APIRouter(prefix="/datasets", tags=["datasets"])

DatasetRepositoryDependency = Annotated[DatasetRepository, Depends(get_repository)]


@router.get("", response_model=list[Dataset])
def list_datasets(repo: DatasetRepositoryDependency):
    return repo.list()


@router.get("/{name}", response_model=Dataset)
def get_dataset(name: str, repo: DatasetRepositoryDependency):
    dataset = repo.get(name)
    if dataset is None:
        raise HTTPException(
            status_code=404,
            detail=f"Dataset not found: {name}"
        )
    return dataset


@router.post("", response_model=Dataset, status_code=201)
def create_dataset(
    dataset: Dataset,
    repo: DatasetRepositoryDependency,
):
    if repo.exists(dataset.name):
        raise HTTPException(
            status_code=409,
            detail=f"Dataset already exists: {dataset.name}",
        )
    return repo.create(dataset.model_dump())


@router.put("/{name}", response_model=Dataset)
def update_dataset(
    name: str,
    dataset: DatasetBase,
    repo: DatasetRepositoryDependency,
):
    updated = repo.update(name, dataset.model_dump())
    if updated is None:
        raise HTTPException(
            status_code=404,
            detail=f"Dataset not found: {name}",
        )
    return updated


@router.delete("/{name}", status_code=204)
def delete_dataset(name: str, repo: DatasetRepositoryDependency):
    if not repo.delete(name):
        raise HTTPException(
            status_code=404,
            detail=f"Dataset not found: {name}",
        )
