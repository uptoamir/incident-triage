"""Exception handlers: every failure leaves through the same envelope."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.envelope import error_response
from app.domain.errors import AppError

_LOCATIONS = {"body", "query", "path", "header"}


def _issue(err: dict) -> dict:
    parts = list(err.get("loc", ()))
    if parts and parts[0] in _LOCATIONS:
        parts = parts[1:]
    value = repr(err.get("input"))
    if len(value) > 120:
        value = value[:117] + "..."
    field = ".".join(str(p) for p in parts) or "request"
    return {"field": field, "issue": err.get("msg", "invalid"), "value": value}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):
        return error_response(
            exc.http_status, exc.code, exc.message, exc.how_to_fix, exc.details, exc.headers
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        raw = exc.errors()
        issues = [_issue(e) for e in raw]
        if raw and all(e.get("type") == "extra_forbidden" and e.get("loc", ("",))[0] == "query" for e in raw):
            names = ", ".join(i["field"] for i in issues)
            return error_response(
                422,
                "unknown_query_parameter",
                f"Unknown query parameter: {names}.",
                ["check the parameter names (see /docs); a typo would otherwise be silently ignored"],
                issues,
            )
        code = "validation_error"
        if any(tuple(e.get("loc", ()))[:2] == ("path", "incident_id") for e in raw):
            code = "invalid_incident_id"
        summary = "; ".join(f"{i['field']}: {i['issue']}" for i in issues[:3]) or "invalid request"
        return error_response(422, code, summary, ["fix the fields listed in details and retry"], issues)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        hint = {
            404: ["check the path; the endpoints are listed at /docs"],
            405: ["check the HTTP method; the endpoints are listed at /docs"],
        }.get(exc.status_code, ["see /docs"])
        return error_response(
            exc.status_code, code, str(exc.detail), hint, headers=getattr(exc, "headers", None)
        )
