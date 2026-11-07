import io
import json
import logging
import re

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.observability.correlation import _pick_id, correlation_id_var
from app.observability.logging import _MARK, JsonFormatter, setup_logging

HEX32 = re.compile(r"^[0-9a-f]{32}$")


def test_ob1_valid_header_is_echoed_and_logged(client, log_lines):
    r = client.get("/health", headers={"X-Correlation-ID": "demo-123"})
    assert r.headers["x-correlation-id"] == "demo-123"
    assert r.json()["correlation_id"] == "demo-123"
    access = [line for line in log_lines() if line["event"] == "http.request"]
    assert access and access[-1]["correlation_id"] == "demo-123"


def test_ob1_missing_header_gets_a_generated_id(client):
    r = client.get("/health")
    assert HEX32.match(r.headers["x-correlation-id"])


@pytest.mark.parametrize("bad", ["bad id", "x" * 200, "semi;colon", "a/b"])
def test_ob1_invalid_header_is_replaced_and_never_logged(client, log_lines, bad):
    r = client.get("/health", headers={"X-Correlation-ID": bad})
    assert HEX32.match(r.headers["x-correlation-id"])
    assert all(bad not in json.dumps(line) for line in log_lines())


def test_ob2_threadpool_and_library_logs_carry_the_id(app, log_lines):
    def sync_route():  # sync on purpose: FastAPI runs it in the threadpool
        logging.getLogger("app.test").info("from route")
        logging.getLogger("uvicorn.error").info("from uvicorn")
        logging.getLogger("openai").info("from openai")
        return {"ok": True}

    app.add_api_route("/_log", sync_route)
    with TestClient(app) as c:
        c.get("/_log", headers={"X-Correlation-ID": "cid-42"})
    by_msg = {line["msg"]: line["correlation_id"] for line in log_lines()}
    assert by_msg["from route"] == "cid-42"
    assert by_msg["from uvicorn"] == "cid-42"
    assert by_msg["from openai"] == "cid-42"


def test_ob3_crash_returns_the_envelope_with_the_id(app):
    def boom():
        raise RuntimeError("secret internals")

    app.add_api_route("/_boom", boom)
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/_boom", headers={"X-Correlation-ID": "cid-500"})
    assert r.status_code == 500
    assert r.headers["x-correlation-id"] == "cid-500"
    err = r.json()["error"]
    assert err["code"] == "internal_error"
    assert err["correlation_id"] == "cid-500"
    assert "secret internals" not in r.text


def test_oversized_body_gets_413_with_the_id(tmp_path):
    s = Settings(_env_file=None, db_path=str(tmp_path / "t.db"), max_request_bytes=1024)
    with TestClient(create_app(s)) as c:
        r = c.post("/health", content=b"x" * 2000, headers={"X-Correlation-ID": "big-1"})
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "payload_too_large"
    assert r.headers["x-correlation-id"] == "big-1"


def test_json_lines_drop_uvicorn_color_message():
    # found by running the real server: uvicorn's ANSI-colored duplicate leaked into the JSON
    record = logging.LogRecord("uvicorn.error", logging.INFO, "x", 0, "Started %d", (1,), None)
    record.color_message = "Started \x1b[36m%d\x1b[0m"
    line = json.loads(JsonFormatter().format(record))
    assert "color_message" not in line
    assert line["msg"] == "Started 1"


def test_unknown_route_uses_the_envelope(client):
    r = client.get("/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


# --- found by the independent review ---


def test_setup_logging_puts_the_id_on_lines_from_every_logger():
    # The log_lines fixture adds its own filter, so the tests above prove the filter class, not the
    # app's wiring: deleting the filter from setup_logging() left them green. This checks the real handler.
    logging.getLogger("uvicorn.error").addHandler(
        logging.StreamHandler(io.StringIO())
    )  # like the uvicorn CLI
    setup_logging("INFO", "json")
    handler = next(h for h in logging.getLogger().handlers if getattr(h, _MARK, False))
    stream = io.StringIO()
    old = handler.setStream(stream)
    token = correlation_id_var.set("cid-real")
    try:
        for name in ("app.anything", "uvicorn.error", "openai", "httpx"):
            logging.getLogger(name).warning("from %s", name)
    finally:
        correlation_id_var.reset(token)
        handler.setStream(old)
    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert {line["msg"]: line["correlation_id"] for line in lines} == {
        f"from {name}": "cid-real" for name in ("app.anything", "uvicorn.error", "openai", "httpx")
    }
    for name in ("uvicorn", "uvicorn.error"):
        assert logging.getLogger(name).handlers == [] and logging.getLogger(name).propagate
    assert logging.getLogger("uvicorn.access").disabled


def test_correlation_id_with_a_trailing_newline_is_refused():
    # re's "$" matches before a trailing "\n", so ^...$ with .match() accepted "abc\n"
    cid, replaced = _pick_id([(b"x-correlation-id", b"abc\n")])
    assert replaced and HEX32.match(cid)
