"""structlog configuration: coloured console in dev, JSON lines in prod."""

from __future__ import annotations

import logging
import sys

import structlog

from aslms.core.config import get_settings


def configure_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    # A console that cannot encode a character (e.g. cp1252 on Windows) must never make logging raise: log
    # lines are written by code paths such as the dev mailer, and a logging error would fail the delivery.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="backslashreplace")
            except (ValueError, OSError):
                pass
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    renderer = structlog.processors.JSONRenderer() if settings.is_prod else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
