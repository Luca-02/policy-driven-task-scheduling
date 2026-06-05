import logging
import json

import uvicorn

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
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
    """Factory function to create the FastAPI app instance."""
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

    @app.middleware("http")
    async def log_requests_and_responses(request: Request, call_next):
        if logger.isEnabledFor(logging.DEBUG):
            body = await request.body()
            logger.debug(
                f"Request: {request.method} {request.url.path} | {body.decode()}"
            )

            async def receive():
                return {"type": "http.request", "body": body, "more_body": False}

            request._receive = receive

        response = await call_next(request)

        if logger.isEnabledFor(logging.DEBUG):
            response_body = b""
            async for chunk in response.body_iterator:
                response_body += chunk

            try:
                pretty = json.dumps(
                    json.loads(response_body), indent=2, ensure_ascii=False
                )
            except (json.JSONDecodeError, ValueError):
                pretty = response_body.decode()

            logger.debug(f"Response: {response.status_code} | {pretty}")

            return Response(
                content=response_body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        return response

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
