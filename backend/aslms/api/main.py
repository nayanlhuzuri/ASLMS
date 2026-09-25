"""FastAPI application. Routers are added one build step at a time (see CLAUDE.md, build order)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from aslms import __version__
from aslms.api.routers import health
from aslms.core.config import get_settings
from aslms.core.errors import AppError
from aslms.core.logging import configure_logging, get_logger

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    log.info("aslms api starting", version=__version__, env=get_settings().app_env)
    yield
    log.info("aslms api stopping")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="ASLMS — Legal Case Monitoring Portal API",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs" if not settings.is_prod else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if not settings.is_prod else None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.public_base_url],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.code, "message": exc.message, "details": exc.details},
        )

    app.include_router(health.router, prefix="/api/v1")
    return app


app = create_app()
