"""Limits from PLAN §12: each one answers with a 422 envelope instead of doing something surprising."""

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import FIXTURE


def _client(tmp_path, **over):
    settings = Settings(_env_file=None, db_path=str(tmp_path / "l.db"), data_path=str(FIXTURE), **over)
    return TestClient(create_app(settings))


def test_ingest_over_the_record_limit_is_422(tmp_path, fixture_records):
    with _client(tmp_path, ingest_max_records=5) as c:
        r = c.post("/ingest", json={"incidents": fixture_records})
    assert r.status_code == 422 and r.json()["error"]["code"] == "too_many_records"


def test_ingest_body_with_an_unknown_key_is_422(client):
    assert client.post("/ingest", json={"records": []}).status_code == 422


def test_question_over_the_configured_limit_is_422(tmp_path):
    with _client(tmp_path, assist_max_question_chars=20) as c:
        r = c.post("/assist", json={"question": "payroll is timing out again in prod"})
    assert r.status_code == 422 and "question" in r.json()["error"]["message"]


def test_q_over_the_configured_limit_is_422(tmp_path):
    with _client(tmp_path, search_max_query_chars=10) as c:
        assert c.get("/search", params={"q": "connection pool exhausted"}).status_code == 422


def test_offset_and_tag_count_limits(client):
    assert client.get("/search", params={"q": "x", "offset": 1001}).status_code == 422
    too_many = [("q", "x")] + [("tags", f"t{i}") for i in range(11)]
    assert client.get("/search", params=too_many).status_code == 422
