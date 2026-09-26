"""Liveness and readiness. `/health` never touches the database; `/ready` does."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from aslms import __version__
from aslms.core.config import get_settings
from aslms.db.session import get_db
from aslms.integration.factory import napix_configured

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__, "env": get_settings().app_env}


@router.get("/ready")
def ready(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {
        "status": "ready",
        "database": "ok",
        "napix": "configured" if napix_configured() else "not configured",
    }
