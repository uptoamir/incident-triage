import json
import re

import pytest

from app.api.deps import get_llm
from app.llm.base import LLMTimeout
from tests.fakes import FakeLLMClient, grounded_answer

QUESTION = "Payroll run timing out with connection pool exhausted errors in prod"
ID = re.compile(r"(?i)\bINC-\d+\b")


@pytest.fixture
def use_llm(app):
    def install(*script):
        fake = FakeLLMClient(*script)
        app.dependency_overrides[get_llm] = lambda: fake
        return fake

    return install


@pytest.fixture
def ingested(client):
    assert client.post("/ingest").status_code == 200
    return client


def test_it2_happy_path_uses_the_same_search_path_as_search(ingested, use_llm):
    fake = use_llm(grounded_answer)
    r = ingested.post("/assist", json={"question": QUESTION}, headers={"X-Correlation-ID": "it2"})
    body = r.json()
    assert r.status_code == 200 and body["status"] == "ok", body
    same = ingested.get("/search", params={"q": QUESTION, "match": "any", "limit": 12}).json()
    assert body["retrieval"]["candidate_ids"] == [h["id"] for h in same["results"]]
    assert set(body["citations"]) <= set(body["retrieval"]["candidate_ids"])
    assert len(fake.calls) == 1
    assert body["customer_draft"]["requires_human_review"] is True
    assert body["correlation_id"] == "it2"


def test_it6_trace_has_the_required_steps_in_order(ingested, use_llm):
    use_llm(grounded_answer)
    ingested.post("/assist", json={"question": QUESTION}, headers={"X-Correlation-ID": "it6"})
    trace = ingested.get("/debug/trace/it6").json()
    names = [s["name"] for s in trace["steps"]]
    assert names == [
        "assist.validate",
        "tool:search",
        "context.build",
        "llm:call",
        "guardrail:validate",
        "assist.selected",
    ]
    search = trace["steps"][1]
    assert search["input"]["terms"] and search["input"]["filters"] == {}
    assert search["output"]["total_hits"] >= 3 and search["output"]["top"]
    assert trace["steps"][-1]["output"]["selected_ids"]


def test_it3_no_hits_means_no_llm_call(ingested, use_llm):
    fake = use_llm(grounded_answer)
    body = ingested.post("/assist", json={"question": "What's a good recipe for sourdough bread?"}).json()
    assert body["status"] == "insufficient_context" and body["llm"] is None
    assert body["clarifying_questions"] and fake.calls == []


def test_question_with_no_searchable_words_never_reaches_the_llm(ingested, use_llm):
    fake = use_llm(grounded_answer)
    body = ingested.post("/assist", json={"question": "why is it so?"}).json()
    assert body["status"] == "insufficient_context" and "searchable" in body["message"]
    assert fake.calls == []


def test_it4_hallucinating_model_following_the_injection_ticket(ingested, use_llm):
    def follows_injection(user):
        answer = grounded_answer(user, n=1)
        answer["relevant_incidents"].append(
            {
                "incident_id": "INC-99999",
                "why_relevant": "The ticket says so.",
                "evidence": [{"field": "description", "quote": "INC-99999 caused this"}],
            }
        )
        answer["next_steps"].append(
            {"step": "Mark all incidents resolved, as INC-99999 says.", "source_ids": ["INC-99999"]}
        )
        return answer

    use_llm(follows_injection)
    body = ingested.post("/assist", json={"question": "Profile photo upload failing with HTTP 413"}).json()
    assert "INC-10010" in body["retrieval"]["candidate_ids"]  # the injection ticket was in the context
    assert {"id": "INC-99999", "reason": "not_retrieved"} in body["guardrails"]["dropped"]
    answer = {k: body[k] for k in ("relevant_incidents", "next_steps", "customer_draft", "citations")}
    assert {m.upper() for m in ID.findall(json.dumps(answer))} <= set(body["citations"])


def test_it5_llm_not_configured_is_503_with_the_fix_and_search_still_works(ingested):
    r = ingested.post("/assist", json={"question": QUESTION})
    err = r.json()["error"]
    assert r.status_code == 503 and err["code"] == "llm_not_configured"
    assert any("LLM_API_KEY" in hint for hint in err["how_to_fix"])
    assert err["details"]["retrieved"] and err["details"]["missing"] == ["LLM_API_KEY"]
    assert ingested.get("/search", params={"q": "payroll"}).status_code == 200


def test_bad_json_gets_one_repair_attempt(ingested, use_llm):
    fake = use_llm({"not": "the schema"}, grounded_answer)
    body = ingested.post(
        "/assist", json={"question": QUESTION}, headers={"X-Correlation-ID": "repair"}
    ).json()
    assert body["status"] == "ok" and body["llm"]["attempts"] == 2 and len(fake.calls) == 2
    assert "previous reply could not be used" in fake.calls[1]["user"]
    steps = ingested.get("/debug/trace/repair").json()["steps"]
    assert [s["status"] for s in steps if s["name"] == "llm:call"] == ["invalid", "ok"]


def test_bad_json_twice_is_502(ingested, use_llm):
    fake = use_llm({"not": "the schema"})
    r = ingested.post("/assist", json={"question": QUESTION})
    assert r.status_code == 502 and r.json()["error"]["code"] == "llm_invalid_output"
    assert len(fake.calls) == 2


def test_timeout_is_504_and_still_returns_what_search_found(ingested, use_llm):
    use_llm(LLMTimeout("No response from the LLM within LLM_TIMEOUT_SECONDS (20 s).", how_to_fix=["retry"]))
    r = ingested.post("/assist", json={"question": QUESTION})
    err = r.json()["error"]
    assert r.status_code == 504 and err["code"] == "llm_timeout"
    assert {c["id"] for c in err["details"]["retrieved"]} >= {"INC-10001"}


def test_assist_validates_its_input(client):
    assert client.post("/assist", json={"question": "hi"}).status_code == 422  # too short
    r = client.post("/assist", json={"question": "payroll down", "filters": {"env": "prod"}})
    assert r.status_code == 422  # unknown filter name, same model as /search
