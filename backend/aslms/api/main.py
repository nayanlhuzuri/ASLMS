"""FastAPI application: all routers under /api/v1, uniform error bodies, CORS for the portal."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from aslms import __version__
from aslms.api.metrics import MetricsMiddleware
from aslms.api.metrics import router as metrics_router
from aslms.api.routers import (
    admin,
    alerts,
    assistant,
    auth,
    cases,
    causelists,
    dashboard,
    health,
    inbox,
    search,
    workflow,
)
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


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Cache-Control", "no-store")
        return response


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
    origins = [settings.public_base_url] + [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(SecurityHeaders)
    app.add_middleware(MetricsMiddleware)

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.code, "message": exc.message, "details": exc.details},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": "validation_error",
                "message": "invalid request",
                "details": {"errors": exc.errors()},
            },
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(
            status_code=422, content={"error": "validation_error", "message": str(exc), "details": {}}
        )

    for r in (health, auth, cases, inbox, search, causelists, alerts, dashboard, admin, workflow, assistant):
        app.include_router(r.router, prefix="/api/v1")
    app.include_router(metrics_router)  # /metrics, scraped by Prometheus on the internal network only
    return app


app = create_app()
