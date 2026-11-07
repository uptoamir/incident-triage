"""Reject oversized bodies before anything reads them."""

import json

from app.api.envelope import error_body


class BodySizeLimitMiddleware:
    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            length = _content_length(scope.get("headers", []))
            if length is not None and length > self.max_bytes:
                body = json.dumps(
                    error_body(
                        "payload_too_large",
                        f"Request body is {length} bytes; the limit is {self.max_bytes}.",
                        ["send a smaller body, or raise MAX_REQUEST_BYTES"],
                    )
                ).encode()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 413,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)


def _content_length(headers: list[tuple[bytes, bytes]]) -> int | None:
    for name, value in headers:
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None
