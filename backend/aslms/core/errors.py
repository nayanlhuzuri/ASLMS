"""Application exceptions. Routers map them to HTTP responses; services raise them."""

from __future__ import annotations


class AppError(Exception):
    status_code = 400
    code = "app_error"

    def __init__(self, message: str = "", **details: object):
        super().__init__(message or self.code)
        self.message = message or self.code
        self.details = details


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"


# --- integration layer ---------------------------------------------------------------------


class IntegrationError(AppError):
    """A remote source misbehaved. Never lost: the caller records it in source_failures."""

    status_code = 502
    code = "integration_error"


class SourceUnavailable(IntegrationError):
    """Down, rate-limited or auth problem — retry later, do not mark records failed."""

    code = "source_unavailable"


class SourceNotFound(IntegrationError):
    """The source has no such record (e.g. NAPIX 628)."""

    status_code = 404
    code = "source_not_found"
