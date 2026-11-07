"""Behaviour added after the independent review (notes/ai-log.md, phase 6)."""

from fastapi.testclient import TestClient

from app.api.deps import get_llm
from app.config import Settings
from app.llm.base import LLMInvalidOutput
from app.main import create_app
from app.search.db import Database
from app.search.repository import SqliteIncidentRepository
from tests.conftest import FIXTURE
from tests.fakes import FakeLLMClient

QUESTION = "Payroll run timing out with connection pool exhausted errors in prod"


def _client(tmp_path, **over):
    return TestClient(
        create_app(Settings(_env_file=None, db_path=str(tmp_path / "r.db"), data_path=str(FIXTURE), **over))
    )


def test_health_is_503_and_logs_the_cause_when_the_db_is_unusable(app, log_lines):
    broken = Database("/nonexistent-dir/incidents.db")
    app.state.db, app.state.repo = broken, SqliteIncidentRepository(broken)
    with TestClient(app) as c:
        r = c.get("/health")
    assert r.status_code == 503
    assert (r.json()["db"], r.json()["fts5"]) == ("error", False)
    assert any(line["event"] == "health.db_error" for line in log_lines())


def test_search_default_limit_comes_from_settings(tmp_path):
    with _client(tmp_path, search_default_limit=2) as c:
        c.post("/ingest")
        body = c.get("/search", params={"q": "certificate deploy pool", "match": "any"}).json()
    assert body["limit"] == 2 and len(body["results"]) == 2 and body["total"] > 2


def test_filter_tags_follow_the_stored_tag_rule(client):
    r = client.get("/search", params={"q": "x", "tags": "x" * 40})
    assert r.status_code == 422


def test_every_error_says_how_to_fix_it(tmp_path):
    with _client(tmp_path, search_max_query_chars=5, assist_max_question_chars=10) as c:
        responses = [
            c.get("/nope"),
            c.get("/ingest"),  # wrong method
            c.get("/search", params={"q": "connection pool"}),
            c.post("/assist", json={"question": "payroll is down again"}),
        ]
    assert [r.status_code for r in responses] == [404, 405, 422, 422]
    assert all(r.json()["error"]["how_to_fix"] for r in responses)


def test_ingest_counts_the_unknown_fields_it_ignored(client, fixture_records):
    records = [{**r, "owner": "someone"} for r in fixture_records[:3]]
    body = client.post("/ingest", json={"incidents": records}).json()
    assert body["ingested"] == 3 and body["ignored_fields"] == {"owner": 3}


def test_model_can_only_cite_incidents_it_was_actually_shown(tmp_path, fixture_records):
    titles = {r["id"]: r["title"] for r in fixture_records}

    def cites_everything(user):
        return {
            "insufficient_context": False,
            "relevant_incidents": [
                {
                    "incident_id": cid,
                    "why_relevant": f"[{cid}]",
                    "evidence": [{"field": "title", "quote": " ".join(t.split()[:5])}],
                }
                for cid, t in titles.items()
            ],
            "next_steps": [],
            "customer_draft": "We're on it.",
            "clarifying_questions": [],
        }

    fake = FakeLLMClient(cites_everything)
    with _client(tmp_path, assist_max_context_chars=1000) as c:  # small budget: some candidates don't fit
        c.app.dependency_overrides[get_llm] = lambda: fake
        c.post("/ingest")
        body = c.post("/assist", json={"question": "certificate deploy pool timeout errors"}).json()
    shown = fake.calls[0]["user"]
    assert body["citations"] and all(f'id="{cid}"' in shown for cid in body["citations"])
    not_shown = {d["id"] for d in body["guardrails"]["dropped"] if d["reason"] == "not_retrieved"}
    assert not_shown and not any(f'id="{cid}"' in shown for cid in not_shown)


def test_a_cut_off_answer_gets_no_repair_call(client, app):
    fake = FakeLLMClient(LLMInvalidOutput("cut off", how_to_fix=["retry"], details={"reason": "truncated"}))
    app.dependency_overrides[get_llm] = lambda: fake
    client.post("/ingest")
    r = client.post("/assist", json={"question": QUESTION})
    assert r.status_code == 502 and r.json()["error"]["code"] == "llm_invalid_output"
    assert len(fake.calls) == 1
