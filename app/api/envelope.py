"""The one error shape every endpoint returns."""

from typing import Any

from fastapi.responses import JSONResponse

from app.observability.correlation import get_correlation_id


def error_body(code: str, message: str, how_to_fix: list[str] | None = None, details: Any = None) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "how_to_fix": how_to_fix or [],
            "details": {} if details is None else details,
            "correlation_id": get_correlation_id(),
        }
    }


def error_response(
    status: int,
    code: str,
    message: str,
    how_to_fix: list[str] | None = None,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(error_body(code, message, how_to_fix, details), status_code=status, headers=headers)
