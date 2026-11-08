"""Drives the Streamlit UI headless against the real API. Needs the API running (`make run`).

    make test-ui

Uses streamlit.testing.AppTest, so it clicks the same buttons a person would. One test calls
the real LLM through /assist (5-15 s).

Streamlit is only imported inside the tests, so `make test` (no ui group) still collects this
file cleanly and just deselects it.
"""

import os
from pathlib import Path

import httpx
import pytest

API = os.environ.get("API_URL", "http://127.0.0.1:8000")
APP = (
    Path(__file__).resolve().parents[2] / "ui" / "app.py"
)  # AppTest resolves relative paths against this file
pytestmark = pytest.mark.ui


@pytest.fixture(scope="module", autouse=True)
def ui_ready():
    pytest.importorskip("streamlit", reason="the ui group isn't installed; run `make test-ui`")
    try:
        httpx.get(f"{API}/health", timeout=3)
    except httpx.HTTPError:
        pytest.skip(f"the API isn't running at {API}; start it with `make run`")


def app():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP), default_timeout=120)
    at.run()
    assert not at.exception, at.exception
    return at


def metrics(at) -> dict[str, str]:
    return {m.label: str(m.value) for m in at.metric}


def test_every_tab_renders():
    assert len(app().tabs) == 7


def test_ingest_twice_shows_idempotency():
    at = app()
    at.button(key="ingest_file").click().run()
    at.button(key="ingest_file").click().run()
    assert not at.exception
    m = metrics(at)
    assert (m["ingested"], m["skipped"]) == ("0", "300")


def test_demo_batch_reports_the_bad_records_and_ignored_fields():
    at = app()
    at.button(key="ingest_batch_btn").click().run()
    assert not at.exception
    assert metrics(at)["invalid"] == "3"
    assert any("owner" in info.value for info in at.info)
    # the request shows up in the sidebar on the same click, not one click later
    assert any("POST /ingest" in md.value for md in at.sidebar.markdown)


def test_search_then_open_a_full_record():
    at = app()
    next(b for b in at.button if b.label == "Search").click().run()
    assert not at.exception
    assert int(metrics(at)["total hits"]) > 0
    next(b for b in at.button if (b.key or "").startswith("open_")).click().run()
    assert not at.exception


def test_assist_end_to_end_with_replay_and_trace():
    at = app()
    at.button(key="assist_ask").click().run()  # the first golden question, real LLM
    assert not at.exception
    at.button(key="assist_replay").click().run()
    assert any("Same candidates" in s.value for s in at.success)
    at.button(key="assist_trace").click().run()
    assert not at.exception


def test_every_error_case_shows_the_envelope():
    at = app()
    at.button(key="errors_all").click().run()
    assert not at.exception
    assert len(at.error) >= 13
