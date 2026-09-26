"""Liveness and readiness. `/health` never touches the database; `/ready` does."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from aslms import __version__
from aslms.api import schemas as S
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


@router.get("/config", response_model=S.ConfigOut)
def config() -> dict[str, object]:
    """Non-secret settings the portal needs (upload limit, feature switches, score thresholds)."""
    from aslms.services.documents import ALLOWED

    s = get_settings()
    return {
        "upload_max_mb": s.upload_max_mb,
        "allowed_upload_types": sorted(ALLOWED),
        "napix_enabled": s.napix_configured,
        "sourcetrace_enabled": s.sourcetrace_enabled,
        "score_strong_threshold": s.score_strong_threshold,
        "score_possible_threshold": s.score_possible_threshold,
        "app_env": s.app_env,
    }
