import logging
import ssl

from fastapi.concurrency import asynccontextmanager
import uvicorn
from fastapi import FastAPI

from src.dependencies import get_config, get_repository
from src.routes.health import router as health_router
from src.routes.provider import router as provider_router
from src.routes.datasets import router as datasets_router

cfg = get_config()

logging.basicConfig(level=cfg.log_level)
logger = logging.getLogger("dataset-service")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- startup ---
    repo = get_repository()
    repo.seed_if_empty(cfg.seed_path, logger)

    # --- run ---
    yield

    # --- shutdown ---
    # nothing to do


app = FastAPI(
    title="Mock Dataset Service",
    description=(
        "Simulates an external dataset catalog. "
        "Implements the Gatekeeper External Data Provider protocol."
    ),
    version="0.1.0",
)

app.include_router(health_router)
app.include_router(provider_router)
app.include_router(datasets_router)


def main():
    # ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    # ssl_ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    # ssl_ctx.load_cert_chain(cfg.TLS_CERT_FILE, cfg.TLS_KEY_FILE)

    uvicorn.run(
        "main:app",
        host=cfg.host,
        port=cfg.port,
        log_level=cfg.log_level.lower(),
        # ssl_keyfile=cfg.TLS_KEY_FILE,
        # ssl_certfile=cfg.TLS_CERT_FILE,
    )


if __name__ == "__main__":
    main()
