"""structlog configuration: key=value console output in development, JSON in production.
Secrets never reach the log: the NAPIX layer logs only the key fingerprint and parameter hashes."""

from __future__ import annotations

import logging
import sys

import structlog

from aslms.core.config import get_settings


def configure_logging() -> None:
    s = get_settings()
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    level = getattr(logging, s.log_level.upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(message)s", stream=sys.stdout)
    # httpx logs every request URL (with the encrypted request_str and dept_id) at INFO: too noisy for the
    # worker and no use for diagnosis — the NAPIX layer logs each call itself without the query string
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    renderer = structlog.processors.JSONRenderer() if s.is_prod else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
