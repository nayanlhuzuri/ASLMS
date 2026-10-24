"""The ASLMS API. `uvicorn aslms.api.main:app` (the Compose `api` service). Settings, the session factory, the
apart-write session factory and the NAPIX request slots live on `app.state` so tests can swap the database (design
`followups-oct`, decisions 2 and 3)."""

from __future__ import annotations

import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI

from aslms import __version__
from aslms.api import metrics as api_metrics
from aslms.api.routers import access as access_router
from aslms.api.routers import alerts as alerts_router
from aslms.api.routers import assistant as assistant_router
from aslms.api.routers import audit as audit_router
from aslms.api.routers import auth as auth_router
from aslms.api.routers import cases as cases_router
from aslms.api.routers import causelists as causelists_router
from aslms.api.routers import dashboard as dashboard_router
from aslms.api.routers import data_load as data_load_router
from aslms.api.routers import discovery as discovery_router
from aslms.api.routers import documents as documents_router
from aslms.api.routers import inbox as inbox_router
from aslms.api.routers import matching as matching_router
from aslms.api.routers import napix_admin as napix_admin_router
from aslms.api.routers import next_dates as next_dates_router
from aslms.api.routers import offices as offices_router
from aslms.api.routers import ownership as ownership_router
from aslms.api.routers import reference as reference_router
from aslms.api.routers import reports as reports_router
from aslms.api.routers import sourcetrace as sourcetrace_router
from aslms.api.routers import system_health as system_health_router
from aslms.api.routers import tickets as tickets_router
from aslms.api.routers import users as users_router
from aslms.api.routers import workflow as workflow_router
from aslms.api.security import jwt_secret
from aslms.core.config import Settings, get_settings
from aslms.core.logging import configure_logging
from aslms.db.session import get_apart_sessionmaker, get_sessionmaker
from aslms.services.db_guard import refuse_superuser


def create_app(settings: Settings | None = None, session_factory=None, apart_session_factory=None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging()
        jwt_secret(settings)  # fail fast without a signing secret
        # design deployment-checklist, decision 5: never serve as a database superuser in production
        refuse_superuser(settings.database_url_sync, is_prod=settings.is_prod)
        # Part B, decision 24: request metrics on the internal port (Compose: 9100; 0 opens nothing)
        api_metrics.start_server(settings.api_metrics_port)
        yield

    # decision 4: the API documentation only in development; app.openapi() still works for the snapshot tool
    docs = settings.app_env == "dev"
    app = FastAPI(
        title="ASLMS — Assam State Litigation Management System",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.state.settings = settings
    app.state.session_factory = session_factory or get_sessionmaker(settings.database_url_sync)
    # the apart writes' own small engine; a test that passes only `session_factory` gets that same factory
    if apart_session_factory is None:
        apart_session_factory = session_factory or get_apart_sessionmaker(
            settings.database_url_sync, settings.db_apart_pool_size, settings.db_apart_pool_timeout_seconds
        )
    app.state.apart_session_factory = apart_session_factory
    app.state.napix_slots = threading.BoundedSemaphore(settings.napix_request_slots)
    app.include_router(auth_router.router)
    app.include_router(users_router.router)
    app.include_router(access_router.router)
    app.include_router(reference_router.router)
    app.include_router(offices_router.router)
    app.include_router(matching_router.router)
    app.include_router(inbox_router.router)
    app.include_router(cases_router.router)
    app.include_router(causelists_router.router)
    app.include_router(documents_router.router)
    documents_router.upload_size_guard(app)
    app.include_router(ownership_router.router)
    app.include_router(alerts_router.router)
    app.include_router(tickets_router.router)
    app.include_router(workflow_router.router)
    app.include_router(sourcetrace_router.router)
    app.include_router(dashboard_router.router)
    app.include_router(reports_router.router)
    app.include_router(audit_router.router)
    app.include_router(napix_admin_router.router)
    app.include_router(data_load_router.router)
    app.include_router(discovery_router.router)
    app.include_router(next_dates_router.router)
    app.include_router(system_health_router.router)
    app.include_router(assistant_router.router)

    api_metrics.install(app)  # last, so it is the outermost middleware

    @app.get("/health", tags=["ops"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
