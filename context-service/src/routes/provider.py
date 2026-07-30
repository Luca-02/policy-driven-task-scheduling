from typing import Annotated

from fastapi import APIRouter, Depends

from src.dependencies import get_issuer_auth_repository
from src.repositories import IssuerAuthRepository
from src.models import Item, ProviderRequest, ProviderResponse, ProviderResponseBody

router = APIRouter(tags=["provider"])

IssuerAuthRepositoryDep = Annotated[
    IssuerAuthRepository, Depends(get_issuer_auth_repository)
]


def make_response(items: list[Item], system_error: str = "") -> ProviderResponse:
    return ProviderResponse(
        response=ProviderResponseBody(items=items, systemError=system_error)
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

    return make_response(items)
