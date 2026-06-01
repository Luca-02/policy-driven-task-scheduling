import logging

import uvicorn

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.concurrency import asynccontextmanager
from sqlalchemy.orm import sessionmaker

from src.config import Config
from src.orm import Base
from src.database import create_engine_factory
from src.routes.health import router as health_router
from src.routes.provider import router as provider_router
from src.routes.datasets import router as datasets_router

load_dotenv()

cfg = Config.from_env()

logging.basicConfig(
    level=getattr(logging, cfg.log_level.upper(), logging.INFO),
    format="[%(asctime)s] %(name)-s [%(levelname)-s] %(message)s",
)
logger = logging.getLogger("dataset-service")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- startup ---
    engine = create_engine_factory(cfg.db_url)

    # Create tables if they don't exist
    Base.metadata.create_all(engine)

    # Create a session factory and store it in the app state
    app.state.session_factory = sessionmaker(
        autocommit=False, autoflush=False, bind=engine
    )

    # --- running ---
    yield

    # --- shutdown ---
    # Dispose the engine to close all connections gracefully
    engine.dispose()


def create_app(custom_cfg: Config | None = None) -> FastAPI:
    """
    Application factory. Builds the session factory from config and wires the
    routers. No seeding is performed here: datasets are loaded out-of-band by
    scripts/seed.py through the public API.
    """
    custom_cfg = custom_cfg or cfg

    app = FastAPI(
        title="Mock Dataset Service",
        description=(
            "Simulates an external dataset catalog. "
            "Implements the Gatekeeper External Data Provider protocol."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    app.include_router(health_router)
    app.include_router(provider_router)
    app.include_router(datasets_router)

    return app


def main():
    kwargs = dict(
        host=cfg.host,
        port=cfg.port,
        log_level=cfg.log_level.lower(),
        # Using the "factory" option to avoid building the app
        # (and opening a DB connection) at import time, so tests
        # can import create_app freely.
        factory=True,
    )

    if cfg.tls_enabled:
        logger.warning(
            "TLS is enabled, make sure to provide valid certificate and key files."
        )
        kwargs["ssl_certfile"] = cfg.tls_cert_file
        kwargs["ssl_keyfile"] = cfg.tls_key_file

    uvicorn.run("main:create_app", **kwargs)


if __name__ == "__main__":
    main()
