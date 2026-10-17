"""The ASLMS API. `uvicorn aslms.api.main:app` (the Compose `api` service). Settings and the session factory
live on `app.state` so tests can swap the database."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from aslms import __version__
from aslms.api.routers import access as access_router
from aslms.api.routers import alerts as alerts_router
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
from aslms.api.routers import tickets as tickets_router
from aslms.api.routers import users as users_router
from aslms.api.routers import workflow as workflow_router
from aslms.api.security import jwt_secret
from aslms.core.config import Settings, get_settings
from aslms.core.logging import configure_logging
from aslms.db.session import get_sessionmaker


def create_app(settings: Settings | None = None, session_factory=None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging()
        jwt_secret(settings)  # fail fast without a signing secret
        yield

    app = FastAPI(title="ASLMS — Legal Case Monitoring Portal", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.session_factory = session_factory or get_sessionmaker(settings.database_url_sync)
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

    @app.get("/health", tags=["ops"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
