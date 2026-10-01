"""Error families. Services catch by family, never by NAPIX code (docs/napix_integration_design.md §6)."""

from __future__ import annotations


class AslmsError(Exception):
    """Base of every application error."""

    def __init__(self, message: str, **details: object):
        super().__init__(message)
        self.message = message
        self.details = details


class IntegrationError(AslmsError):
    """An outside system (NAPIX, SourceTrace, mail…) could not be used. `napix_status` and `api` are set
    for NAPIX errors."""

    def __init__(
        self, message: str, *, napix_status: int | None = None, api: str | None = None, **details: object
    ):
        super().__init__(message, napix_status=napix_status, api=api, **details)
        self.napix_status = napix_status
        self.api = api


class NapixNotFound(IntegrationError):
    """600 INVALID_CNR, 628 RECORD_NOT_FOUND: a valid call that found no data. Not retried."""


class NapixUnavailable(IntegrationError):
    """629 UNEXPECTED_ERROR, HTTP 429 / 5xx, time-outs, connection errors. Retried with back-off."""


class NapixAuthError(IntegrationError):
    """626 INVALID_TOKEN, 627 INVALID_DEPT_ID, a second 401: the key or credentials are wrong. Not retried;
    the operator must act."""


class NapixGatewayError(IntegrationError):
    """The gateway answered instead of eCourts (httpCode body, 'Cannot find valid subscription') or 631
    API_ACCESS_NOT_ALLOWED: a wrong path or an unsubscribed product. Not retried."""


class NapixInputError(IntegrationError):
    """601–604, 616, 632–634: our parameters are wrong. Not retried."""


class NapixProtocolError(IntegrationError):
    """An envelope that cannot be read: undecryptable payload, unknown shape, unparsable body."""
