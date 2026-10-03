"""The ASLMS API. `uvicorn aslms.api.main:app` (the Compose `api` service). Settings and the session factory
live on `app.state` so tests can swap the database."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from aslms import __version__
from aslms.api.routers import access as access_router
from aslms.api.routers import auth as auth_router
from aslms.api.routers import users as users_router
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

    @app.get("/health", tags=["ops"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
