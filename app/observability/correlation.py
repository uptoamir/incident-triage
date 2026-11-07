"""Correlation ID per request: read or generate it, keep it in a ContextVar, echo it back."""

import json
import logging
import re
import time
import uuid
from contextvars import ContextVar

log = logging.getLogger("app.http")

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="-")
_VALID_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")  # used with fullmatch: "$" would accept "abc\n"


def get_correlation_id() -> str:
    return correlation_id_var.get()


def _pick_id(headers: list[tuple[bytes, bytes]]) -> tuple[str, bool]:
    """Return (id, replaced). replaced=True means the client sent a value we refused."""
    sent = None
    for wanted in (b"x-correlation-id", b"x-request-id"):
        sent = next((value for name, value in headers if name == wanted), None)
        if sent is not None:
            break
    if sent is not None:
        try:
            value = sent.decode("ascii")
        except UnicodeDecodeError:
            value = ""
        if _VALID_ID.fullmatch(value):
            return value, False
    return uuid.uuid4().hex, sent is not None


class CorrelationIdMiddleware:
    """Pure ASGI on purpose, and it has to be the outermost user middleware.

    Starlette's ServerErrorMiddleware sits outside user middleware, so if an exception
    escapes, the 500 it builds has no correlation header. We catch it here instead.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        cid, replaced = _pick_id(scope.get("headers", []))
        token = correlation_id_var.set(cid)
        started = time.perf_counter()
        state = {"status": 500, "response_started": False}

        async def send_with_id(message):
            if message["type"] == "http.response.start":
                state["response_started"] = True
                state["status"] = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-correlation-id", cid.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            if replaced:
                # never log the raw value: it's attacker-controlled
                log.info("invalid correlation id header replaced", extra={"event": "correlation_id_replaced"})
            await self.app(scope, receive, send_with_id)
        except Exception:
            log.exception("unhandled error", extra={"event": "http.unhandled_error"})
            if not state["response_started"]:
                await _send_internal_error(send_with_id, cid)
            state["status"] = 500
        finally:
            log.info(
                "%s %s -> %s",
                scope.get("method"),
                scope.get("path"),
                state["status"],
                extra={
                    "event": "http.request",
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status": state["status"],
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
            correlation_id_var.reset(token)


async def _send_internal_error(send, cid: str) -> None:
    # same shape as app/api/envelope.py; built inline so observability doesn't import the api layer
    body = json.dumps(
        {
            "error": {
                "code": "internal_error",
                "message": "Something went wrong on our side.",
                "how_to_fix": ["retry; if it keeps failing, search the server logs for this correlation_id"],
                "details": {},
                "correlation_id": cid,
            }
        }
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 500,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": body})
