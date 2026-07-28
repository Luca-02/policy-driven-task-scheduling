from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from src.dependencies import get_repository
from src.repositories import ContextRepository
from src.models import Conflict, ConflictPair
from src.exceptions import AlreadyExistsError, WellFormednessViolation

router = APIRouter(prefix="/conflicts", tags=["conflicts"])

ContextRepositoryDep = Annotated[ContextRepository, Depends(get_repository)]


@router.get("", response_model=list[Conflict])
def get_all_conflicts(repo: ContextRepositoryDep):
    return repo.get_all_conflicts()


@router.post("", response_model=Conflict, status_code=201)
def create_conflict(pair: ConflictPair, repo: ContextRepositoryDep):
    try:
        return repo.create_conflict(pair)
    except AlreadyExistsError:
        raise HTTPException(
            status_code=409,
            detail=f"Conflict already exists: {pair.context_a} | {pair.context_b}",
        )
    except WellFormednessViolation as exc:
        raise HTTPException(
            status_code=409,
            detail={"msg": str(exc), "issuers": exc.issuers},
        )


@router.delete("/{context_a}/{context_b}", status_code=204)
def delete_conflict(context_a: str, context_b: str, repo: ContextRepositoryDep):
    if not repo.delete_conflict(context_a, context_b):
        raise HTTPException(
            status_code=404,
            detail=f"Conflict not found: {context_a} | {context_b}",
        )


@router.delete("", status_code=204)
def delete_all_conflicts(repo: ContextRepositoryDep):
    count = repo.delete_all_conflicts()
    if count == 0:
        raise HTTPException(status_code=404, detail="No conflicts to delete")
