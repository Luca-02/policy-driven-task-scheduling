from fastapi import APIRouter

router = APIRouter(tags=["healthz"])


@router.get("/healthz")
def healthz():
    return {"status": "ok"}
