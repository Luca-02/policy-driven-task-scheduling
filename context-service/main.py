import logging
import json

import uvicorn

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.concurrency import asynccontextmanager
from sqlalchemy.orm import sessionmaker

from src.config import Config
from src.orm import Base, LockORM
from src.database import create_engine_factory
from src.routes.healthz import router as health_router
from src.routes.provider import router as provider_router
from src.routes.issuer_auths import router as issuer_auths_router
from src.routes.conflicts import router as conflicts_router

load_dotenv()

cfg = Config.from_env()

logging.basicConfig(
    level=getattr(logging, cfg.log_level.upper(), logging.INFO),
    format="[%(asctime)s] %(name)-s [%(levelname)-s] %(message)s",
)
logger = logging.getLogger("context-service")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- startup ---
    config: Config = app.state.config
    engine = create_engine_factory(config.db_url)

    # Create tables if they don't exist
    Base.metadata.create_all(engine)

    # Create a session factory and store it in the app state
    app.state.session_factory = sessionmaker(
        autocommit=False, autoflush=False, bind=engine
    )

    # Seed the sentinel row used by ContextRepository._acquire_lock to
    # serialize writes that must preserve the well-formedness invariant.
    with app.state.session_factory() as db:
        if db.get(LockORM, 1) is None:
            db.add(LockORM(id=1))
            db.commit()

    # --- running ---
    yield

    # --- shutdown ---
    # Dispose the engine to close all connections gracefully
    engine.dispose()


def create_app(custom_cfg: Config | None = None) -> FastAPI:
    """Factory function to create the FastAPI app instance."""
    custom_cfg = custom_cfg or cfg

    app = FastAPI(
        title="Mock Context Service",
        description=(
            "Simulates an external context/authorization catalog: issuer "
            "authorizations (auth) and the context conflict-of-interest "
            "relation (X_conf). Implements the Gatekeeper External Data "
            "Provider protocol."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    app.state.config = custom_cfg

    app.include_router(health_router)
    app.include_router(provider_router)
    app.include_router(issuer_auths_router)
    app.include_router(conflicts_router)

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
