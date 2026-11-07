"""Errors services raise. app/api/errors.py turns them into the error envelope."""

from typing import Any


class AppError(Exception):
    http_status = 500
    code = "internal_error"

    def __init__(
        self,
        message: str,
        *,
        how_to_fix: list[str] | None = None,
        details: Any = None,
        code: str | None = None,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.how_to_fix = how_to_fix or []
        self.details = {} if details is None else details
        self.headers = headers
        if code:
            self.code = code


class InvalidRequest(AppError):
    """The client sent something we can't accept (beyond what request-model validation catches)."""

    http_status = 422
    code = "validation_error"


class NotFound(AppError):
    http_status = 404
    code = "not_found"


class DataSourceError(AppError):
    http_status = 503
    code = "data_source_error"
