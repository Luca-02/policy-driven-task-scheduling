from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from src.dependencies import get_conflict_repository
from src.repositories import ConflictRepository
from src.models import Conflict, ConflictPair
from src.exceptions import AlreadyExistsError, NotFoundError, WellFormednessViolation

router = APIRouter(prefix="/conflicts", tags=["conflicts"])

ConflictRepositoryDep = Annotated[ConflictRepository, Depends(get_conflict_repository)]


@router.get("", response_model=list[Conflict])
def get_all_conflicts(repo: ConflictRepositoryDep):
    return repo.get_all()


@router.get("/{context}", response_model=list[Conflict])
def get_conflicts_for_context(context: str, repo: ConflictRepositoryDep):
    return repo.get_for_context(context)


@router.post("", response_model=Conflict, status_code=201)
def create_conflict(pair: ConflictPair, repo: ConflictRepositoryDep):
    try:
        return repo.create(pair)
    except AlreadyExistsError:
        raise HTTPException(
            status_code=409,
            detail=f"Conflict already exists: {pair}",
        )
    except WellFormednessViolation as exc:
        raise HTTPException(status_code=409, detail=exc.details())


@router.post("/batch", response_model=list[Conflict], status_code=201)
def create_conflicts_batch(pairs: list[ConflictPair], repo: ConflictRepositoryDep):
    try:
        return repo.create_batch(pairs)
    except AlreadyExistsError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Conflict already exists: {exc.name}",
        )
    except WellFormednessViolation as exc:
        raise HTTPException(status_code=409, detail=exc.details())


@router.delete("/{context_a}/{context_b}", status_code=204)
def delete_conflict(context_a: str, context_b: str, repo: ConflictRepositoryDep):
    try:
        pair = ConflictPair(context_a=context_a, context_b=context_b)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid conflict pair: contexts must be distinct",
        )

    try:
        repo.delete(pair)
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"Conflict not found: {pair}")


@router.delete("", status_code=204)
def delete_all_conflicts(repo: ConflictRepositoryDep):
    count = repo.delete_all()
    if count == 0:
        raise HTTPException(status_code=404, detail="No conflicts to delete")
