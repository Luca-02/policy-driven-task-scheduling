from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from src.config import Config
from src.dependencies import get_config, get_issuer_auth_repository
from src.repositories import IssuerAuthRepository
from src.models import (
    Item,
    IssuerAuth,
    IssuerAuthBase,
    IssuerAuthQuery,
    ProviderResponse,
    WallCheckRequest,
    WallCheckResponse,
    ProviderRequest,
    ProviderResponse,
    ProviderResponseBody,
)
from src.exceptions import AlreadyExistsError, NotFoundError, WellFormednessViolation

router = APIRouter(prefix="/issuer-auths", tags=["issuer-auths"])

IssuerAuthRepositoryDep = Annotated[
    IssuerAuthRepository, Depends(get_issuer_auth_repository)
]


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


@router.get("", response_model=list[IssuerAuth])
def get_all_issuer_auths(repo: IssuerAuthRepositoryDep):
    return repo.get_all()


@router.get("/{name}", response_model=IssuerAuth)
def get_issuer_auth(name: str, repo: IssuerAuthRepositoryDep):
    issuer_auth = repo.get(name)
    if issuer_auth is None:
        raise HTTPException(
            status_code=404,
            detail=f"Issuer authorization not found: {name}",
        )
    return issuer_auth


@router.post("/query", response_model=list[IssuerAuth])
def query_issuer_auths(query: IssuerAuthQuery, repo: IssuerAuthRepositoryDep):
    result = repo.query(query.keys)
    if len(result) != len(query.keys):
        found_keys = {issuer_auth.name for issuer_auth in result}
        missing_keys = set(query.keys) - found_keys
        raise HTTPException(
            status_code=404,
            detail=f"Issuer authorizations not found: {', '.join(missing_keys)}",
        )
    return result


@router.post("/{name}/wall-check", response_model=WallCheckResponse)
def check_wall_conflicts(
    name: str,
    body: WallCheckRequest,
    repo: IssuerAuthRepositoryDep,
):
    try:
        conflicts = repo.wall_conflicts(name, body.contexts)
        return WallCheckResponse(conflicts=conflicts)
    except NotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Issuer authorization not found: {name}",
        )


@router.post("", response_model=IssuerAuth, status_code=201)
def create_issuer_auth(issuer_auth: IssuerAuth, repo: IssuerAuthRepositoryDep):
    try:
        return repo.create(issuer_auth)
    except AlreadyExistsError:
        raise HTTPException(
            status_code=409,
            detail=f"Issuer authorization already exists: {issuer_auth.name}",
        )
    except WellFormednessViolation as exc:
        raise HTTPException(status_code=409, detail=exc.details())


@router.post("/batch", response_model=list[IssuerAuth], status_code=201)
def create_issuer_auths(issuer_auths: list[IssuerAuth], repo: IssuerAuthRepositoryDep):
    try:
        return repo.create_batch(issuer_auths)
    except AlreadyExistsError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Issuer authorization already exists: {exc.name}",
        )
    except WellFormednessViolation as exc:
        raise HTTPException(status_code=409, detail=exc.details())


@router.put(
    "/{name}",
    response_model=IssuerAuth,
    dependencies=[Depends(verify_debug_mode)],
)
def update_issuer_auth(
    name: str,
    issuer_auth: IssuerAuthBase,
    repo: IssuerAuthRepositoryDep,
):
    """
    Debug-only endpoints. It ensure that the assumption of immutability of
    metadata is respected. These endpoints are not meant to be used in production,
    but only for testing and debugging purposes.

    This will mitigate the `Time-of-check to Time-of-use` race condition that can
    occur when updating metadata.
    """
    try:
        updated = repo.update(name, issuer_auth)
    except WellFormednessViolation as exc:
        raise HTTPException(status_code=409, detail=exc.details())
    if updated is None:
        raise HTTPException(
            status_code=404,
            detail=f"Issuer authorization not found: {name}",
        )
    return updated


@router.delete("/{name}", status_code=204)
def delete_issuer_auth(name: str, repo: IssuerAuthRepositoryDep):
    try:
        repo.delete(name)
    except NotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Issuer authorization not found: {name}",
        )


@router.delete("", status_code=204)
def delete_all_issuer_auths(repo: IssuerAuthRepositoryDep):
    count = repo.delete_all()
    if count == 0:
        raise HTTPException(
            status_code=404,
            detail="No issuer authorizations to delete",
        )


@router.post("/validate", response_model=ProviderResponse)
def validate(req: ProviderRequest, repo: IssuerAuthRepositoryDep):
    """Resolves issuer existence and auth(i) for OPA Gatekeeper."""
    items = []
    issuer_auths = repo.query(req.request.keys)
    issuer_auths_dict = {issuer_auth.name: issuer_auth for issuer_auth in issuer_auths}

    for key in req.request.keys:
        issuer_auth = issuer_auths_dict.get(key)
        if issuer_auth is None:
            items.append(Item(key=key, error=f"Issuer {key!r} not found"))
            continue

        items.append(
            Item(
                key=key,
                value=issuer_auth.model_dump(exclude_none=True),
            )
        )

    return ProviderResponse(response=ProviderResponseBody(items=items, systemError=""))
