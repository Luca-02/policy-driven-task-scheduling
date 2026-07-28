from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from src.dependencies import get_repository
from src.repositories import ContextRepository
from src.models import Issuer, IssuerBase, IssuerQuery
from src.exceptions import AlreadyExistsError, WellFormednessViolation

_RESPONSE_MODEL_KWARGS = {"response_model_exclude_none": True}

router = APIRouter(prefix="/issuers", tags=["issuers"])

ContextRepositoryDep = Annotated[ContextRepository, Depends(get_repository)]


def _well_formedness_detail(exc: WellFormednessViolation) -> dict:
    detail = {"msg": str(exc)}
    if exc.conflicts:
        detail["conflicts"] = [list(pair) for pair in exc.conflicts]
    if exc.issuers:
        detail["issuers"] = exc.issuers
    return detail


@router.get("", response_model=list[Issuer], **_RESPONSE_MODEL_KWARGS)
def get_all_issuers(repo: ContextRepositoryDep):
    return repo.get_all_issuers()


@router.get("/{name}", response_model=Issuer, **_RESPONSE_MODEL_KWARGS)
def get_issuer(name: str, repo: ContextRepositoryDep):
    issuer = repo.get_issuer(name)
    if issuer is None:
        raise HTTPException(status_code=404, detail=f"Issuer not found: {name}")
    return issuer


@router.post("/query", response_model=list[Issuer], **_RESPONSE_MODEL_KWARGS)
def query_issuers(query: IssuerQuery, repo: ContextRepositoryDep):
    result = repo.query_issuers(query.keys)
    if len(result) != len(query.keys):
        found_keys = {issuer.name for issuer in result}
        missing_keys = set(query.keys) - found_keys
        raise HTTPException(
            status_code=404,
            detail=f"Issuers not found: {', '.join(missing_keys)}",
        )
    return result


@router.post("", response_model=Issuer, status_code=201, **_RESPONSE_MODEL_KWARGS)
def create_issuer(issuer: Issuer, repo: ContextRepositoryDep):
    try:
        return repo.create_issuer(issuer)
    except AlreadyExistsError:
        raise HTTPException(
            status_code=409, detail=f"Issuer already exists: {issuer.name}"
        )
    except WellFormednessViolation as exc:
        raise HTTPException(status_code=409, detail=_well_formedness_detail(exc))


@router.post(
    "/batch", response_model=list[Issuer], status_code=201, **_RESPONSE_MODEL_KWARGS
)
def create_issuers(issuers: list[Issuer], repo: ContextRepositoryDep):
    try:
        return repo.create_issuers_batch(issuers)
    except AlreadyExistsError as exc:
        raise HTTPException(
            status_code=409, detail=f"Issuer already exists: {exc.name}"
        )
    except WellFormednessViolation as exc:
        raise HTTPException(status_code=409, detail=_well_formedness_detail(exc))


# TODO: Add versioning support for the assumption of immutability of
# metadata, mirroring the same open point in dataset-service. This will
# mitigate the Time-of-check to Time-of-use race condition that can occur
# when updating metadata.
@router.put("/{name}", response_model=Issuer, **_RESPONSE_MODEL_KWARGS)
def update_issuer(name: str, issuer: IssuerBase, repo: ContextRepositoryDep):
    try:
        updated = repo.update_issuer(name, issuer)
    except WellFormednessViolation as exc:
        raise HTTPException(status_code=409, detail=_well_formedness_detail(exc))
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Issuer not found: {name}")
    return updated


@router.delete("/{name}", status_code=204)
def delete_issuer(name: str, repo: ContextRepositoryDep):
    if not repo.delete_issuer(name):
        raise HTTPException(status_code=404, detail=f"Issuer not found: {name}")


@router.delete("", status_code=204)
def delete_all_issuers(repo: ContextRepositoryDep):
    count = repo.delete_all_issuers()
    if count == 0:
        raise HTTPException(status_code=404, detail="No issuers to delete")
