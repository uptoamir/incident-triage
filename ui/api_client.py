"""Thin HTTP client for the UI. No Streamlit in here.

Every call gets its own correlation id, so the trace view can find exactly that request,
and every exchange can print the equivalent curl command.
"""

import json
import shlex
import uuid
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class Exchange:
    method: str
    path: str
    url: str
    correlation_id: str
    request_body: Any
    status: int | None
    response: Any
    elapsed_ms: float
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is not None and self.status < 400

    def curl(self) -> str:
        parts = ["curl -s"]
        if self.method != "GET":
            parts.append(f"-X {self.method}")
        parts.append(shlex.quote(self.url))
        parts.append("-H " + shlex.quote(f"X-Correlation-ID: {self.correlation_id}"))
        if self.request_body is not None:
            parts.append("-H 'Content-Type: application/json'")
            parts.append("-d " + shlex.quote(json.dumps(self.request_body)))
        return " ".join(parts)


class ApiClient:
    def __init__(self, base_url: str, timeout_s: float = 90.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s  # /assist can take 5-15 s; the server caps its own LLM time at 45 s

    def request(
        self, method: str, path: str, *, params: dict | None = None, json_body: Any = None
    ) -> Exchange:
        cid = f"ui-{uuid.uuid4().hex[:10]}"
        url = self.base_url + path
        try:
            r = httpx.request(
                method,
                url,
                params=params,
                json=json_body,
                headers={"X-Correlation-ID": cid},
                timeout=self.timeout_s,
            )
        except httpx.HTTPError as exc:
            return Exchange(
                method, path, url, cid, json_body, None, None, 0.0, f"{type(exc).__name__}: {exc}"
            )
        try:
            body = r.json()
        except ValueError:
            body = r.text
        return Exchange(
            method=method,
            path=path,
            url=str(r.request.url),
            correlation_id=r.headers.get("x-correlation-id", cid),
            request_body=json_body,
            status=r.status_code,
            response=body,
            elapsed_ms=r.elapsed.total_seconds() * 1000,
        )
