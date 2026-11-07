"""Guardrails G1-G9 (PLAN §9.5). Written before app/assist/guardrails.py existed."""

import json
import re

import pytest

from app.assist.guardrails import apply
from app.assist.llm_schema import AssistLLMOutput

ID_PATTERN = r"(?i)\bINC-\d+\b"
DEFAULT_QUESTIONS = ["Which service?", "What exact error do you see?"]

# real quotes from tests/fixtures/incidents_small.json
QUOTES = {
    "INC-10001": ("description", "workers hit ERR-5003 connection pool exhausted"),
    "INC-10002": ("description", "timeout acquiring connection after 30000 ms"),
    "INC-10003": ("title", "requests timing out, pool exhausted"),
    "INC-10004": ("resolution_summary", "Renewed the certificate"),
    "INC-10005": ("description", "failed with ERR-4401 certificate has expired"),
    "INC-10006": ("title", "returning 500 errors after release 3.2.0"),
    "INC-10007": ("description", "caused HTTP 500 on every save"),
}


@pytest.fixture
def candidates(fixture_records):
    return {r["id"]: r for r in fixture_records}


def rel(incident_id, quote=None, field=None, why=None):
    f, q = QUOTES.get(incident_id, ("description", "a quote that is nowhere in any record"))
    return {
        "incident_id": incident_id,
        "why_relevant": why or f"Same symptom [{incident_id}].",
        "evidence": [{"field": field or f, "quote": quote or q}],
    }


def output(rels, steps=None, draft="We're on it. We'll share an update by [time of next update].", **over):
    data = {
        "insufficient_context": False,
        "relevant_incidents": rels,
        "next_steps": steps
        if steps is not None
        else [{"step": "Check pool saturation.", "source_ids": ["INC-10001"]}],
        "customer_draft": draft,
        "clarifying_questions": [],
    }
    data.update(over)
    return AssistLLMOutput.model_validate(data)


def run(out, candidates, mode="strict", question="payroll pool timeouts"):
    return apply(
        out, candidates, question, mode=mode, id_pattern=ID_PATTERN, default_questions=DEFAULT_QUESTIONS
    )


def ids_mentioned(result) -> set[str]:
    return {m.upper() for m in re.findall(ID_PATTERN, json.dumps(result))}


def test_gr1_ids_that_were_not_retrieved_are_dropped(candidates):
    out = output([rel("INC-10001"), rel("INC-9999"), rel("INC-123456"), rel("INC-00999"), rel("INC-10001")])
    result, report = run(out, candidates)
    assert result["citations"] == ["INC-10001"]
    assert {d["id"] for d in report.dropped if d["reason"] == "not_retrieved"} == {
        "INC-9999",
        "INC-123456",
        "INC-00999",
    }
    # facts come from the database, not the model (G8)
    assert result["relevant_incidents"][0]["title"] == candidates["INC-10001"]["title"]


def test_gr2_text_may_only_mention_finally_kept_incidents(candidates):
    out = output(
        [
            rel("INC-10001", why="Same pool errors as inc-00999 [INC-10001]."),
            rel("INC-10002", quote="words that are not in that record at all"),  # dropped by G4
        ],
        steps=[
            {
                "step": "Raise the pool like INC-10002 did.",
                "source_ids": ["INC-10001"],
            },  # names a dropped incident
            {"step": "Check pool saturation [INC-10001].", "source_ids": ["INC-10001"]},
        ],
        draft="This looks like INC-10001. We'll update you by [time of next update].",
    )
    result, report = run(out, candidates)
    assert result["citations"] == ["INC-10001"]
    assert "[reference removed]" in result["relevant_incidents"][0]["why_relevant"]
    assert [s["step"] for s in result["next_steps"]] == ["Check pool saturation [INC-10001]."]
    assert "INC-10001" not in result["customer_draft"]["text"]
    assert ids_mentioned(result) <= set(result["citations"])


def test_gr3_unverifiable_evidence_strict_drops_lenient_flags(candidates):
    bad = rel("INC-10001", quote="pool exhausted because of cosmic rays")
    strict, report = run(output([bad]), candidates, mode="strict")
    assert strict["citations"] == [] and report.dropped == [
        {"id": "INC-10001", "reason": "evidence_not_verified"}
    ]
    lenient, report = run(output([bad]), candidates, mode="lenient")
    assert lenient["citations"] == ["INC-10001"]
    assert lenient["relevant_incidents"][0]["evidence"][0]["verified"] is False
    assert report.unverified_evidence == ["INC-10001"]


def test_gr4_one_verified_quote_is_enough_and_matching_is_normalized(candidates):
    two = rel("INC-10001")
    two["evidence"].append({"field": "description", "quote": "this second quote is invented"})
    curly = rel("INC-10002", quote="“TIMEOUT   acquiring connection after 30000 ms.”")
    short = rel("INC-10003", quote="pool exhausted", field="title")
    result, _ = run(output([two, curly, short]), candidates)
    assert result["citations"] == ["INC-10001", "INC-10002"]
    verified = [e["verified"] for e in result["relevant_incidents"][0]["evidence"]]
    assert verified == [True, False]


def test_gr5_step_sources_general_steps_and_the_fallback(candidates):
    out = output(
        [rel("INC-10001"), rel("INC-10002", quote="not in the record at all, honestly")],
        steps=[
            {
                "step": "Do what the stage fix did.",
                "source_ids": ["INC-10002"],
            },  # its only source got dropped
            {"step": "Raise the pool size.", "source_ids": ["INC-10001", "INC-10002"]},
            {"step": "Confirm the start time.", "source_ids": []},
            {"step": "Check recent deploys.", "source_ids": []},
            {"step": "Ask about user impact.", "source_ids": []},  # third general step: over the cap
        ],
    )
    result, _ = run(out, candidates)
    assert [(s["step"], s["source_ids"], s["kind"]) for s in result["next_steps"]] == [
        ("Raise the pool size.", ["INC-10001"], "from_incidents"),
        ("Confirm the start time.", [], "general"),
        ("Check recent deploys.", [], "general"),
    ]
    none_left, report = run(
        output([rel("INC-10001")], steps=[{"step": "x", "source_ids": ["INC-77777"]}]), candidates
    )
    assert len(none_left["next_steps"]) == 2 and all(s["kind"] == "general" for s in none_left["next_steps"])
    assert any("fallback" in w for w in report.warnings)


def test_gr6_counts_and_status(candidates):
    seven = [rel(i) for i in QUOTES]
    assert run(output(seven), candidates)[0]["status"] == "ok"
    assert len(run(output(seven), candidates)[0]["citations"]) == 5
    assert run(output([rel("INC-10001"), rel("INC-10002")]), candidates)[0]["status"] == "partial"
    empty, _ = run(output([], steps=[]), candidates)
    assert empty["status"] == "insufficient_context"
    assert empty["clarifying_questions"] == DEFAULT_QUESTIONS
    assert empty["customer_draft"] is None and empty["next_steps"] == []
    # the model's own "nothing relevant" flag can only make the status stricter
    flagged, _ = run(
        output(seven[:3], insufficient_context=True, clarifying_questions=["Which tenant?"]), candidates
    )
    assert flagged["status"] == "insufficient_context"
    assert flagged["citations"] == [] and flagged["clarifying_questions"] == ["Which tenant?"]


def test_gr7_customer_draft_hygiene(candidates):
    long_draft = "We are looking into INC-10001 for you. " + "More words here. " * 200
    result, _ = run(output([rel("INC-10001")], draft=long_draft), candidates)
    draft = result["customer_draft"]
    assert "INC-10001" not in draft["text"] and len(draft["text"]) <= 1200
    assert draft["requires_human_review"] is True and draft["based_on"] == ["INC-10001"]
    blank, _ = run(output([rel("INC-10001")], draft="   "), candidates)
    assert blank["customer_draft"]["text"].strip()


def test_gr8_specific_values_check_warns_but_never_drops(candidates):
    out = output([rel("INC-10001", why="Same ERR-5003 and ERR-7777 errors as before [INC-10001].")])
    result, report = run(out, candidates)
    assert result["citations"] == ["INC-10001"]
    assert "ERR-7777" in report.unsupported_specifics
    assert "ERR-5003" not in report.unsupported_specifics  # it's in the cited record
    assert not any(s.upper().startswith("INC-") for s in report.unsupported_specifics)
