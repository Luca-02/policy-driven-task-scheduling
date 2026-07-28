from typing import Annotated

from fastapi import APIRouter, Depends

from src.dependencies import get_repository
from src.repositories import ContextRepository
from src.models import Item, ProviderRequest, ProviderResponse, ProviderResponseBody

router = APIRouter(tags=["provider"])

ContextRepositoryDep = Annotated[ContextRepository, Depends(get_repository)]


def make_response(items: list[Item], system_error: str = "") -> ProviderResponse:
    return ProviderResponse(
        response=ProviderResponseBody(items=items, systemError=system_error)
    )


@router.post("/validate", response_model=ProviderResponse)
def validate(
    req: ProviderRequest,
    repo: ContextRepositoryDep,
):
    """
    Resolves issuer existence and auth(i) for OPA Gatekeeper.
    """
    items = []
    issuers = repo.query_issuers(req.request.keys)
    issuers_dict = {issuer.name: issuer for issuer in issuers}

    for key in req.request.keys:
        issuer = issuers_dict.get(key)
        if issuer is None:
            items.append(Item(key=key, error=f"Issuer '{key}' not found"))
            continue

        items.append(Item(key=key, value={"contexts": issuer.contexts}))

    return make_response(items)
