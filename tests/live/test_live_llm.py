"""Real LLM, real data: `make test-live`. Skipped when no LLM key is configured (reads .env).

Checks invariants only, never exact wording, so it holds up when the model phrases things differently.
"""

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.assist.guardrails import fold
from app.config import Settings
from app.main import create_app

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = json.loads((ROOT / "data/golden.json").read_text(encoding="utf-8"))
ID = re.compile(r"(?i)\bINC-\d+\b")


@pytest.fixture(scope="module")
def live_client(tmp_path_factory):
    settings = Settings(
        db_path=str(tmp_path_factory.mktemp("live") / "live.db"), data_path=str(ROOT / "data/incidents.json")
    )
    if missing := settings.llm_missing_vars():
        pytest.skip(f"LLM not configured (missing {', '.join(missing)})")
    with TestClient(create_app(settings)) as client:
        assert client.post("/ingest").json()["ingested"] == 300
        yield client


@pytest.mark.live
@pytest.mark.parametrize("case", GOLDEN, ids=[f"{g['kind']}-{i}" for i, g in enumerate(GOLDEN)])
def test_live_golden_question_keeps_the_invariants(live_client, case):
    r = live_client.post("/assist", json={"question": case["question"]})
    assert r.status_code == 200, r.text
    body = r.json()
    # every string the model wrote, after folding lookalike dashes, may only name cited incidents
    texts = list(body["clarifying_questions"])
    for inc in body["relevant_incidents"]:
        texts += [inc["why_relevant"], *(e["quote"] for e in inc["evidence"])]
    texts += [s["step"] for s in body["next_steps"]]
    texts += [body["customer_draft"]["text"]] if body["customer_draft"] else []
    assert {m.upper() for m in ID.findall(fold(" ".join(texts)))} <= set(body["citations"])
    assert set(body["citations"]) <= set(body["retrieval"]["candidate_ids"])
    if body["customer_draft"]:
        assert not ID.search(body["customer_draft"]["text"])
    if case["kind"] == "match":
        assert body["status"] in ("ok", "partial"), body
        assert set(body["citations"]) & set(case["expected_ids"]), body["citations"]
    elif case["kind"] == "no_match":
        assert body["status"] == "insufficient_context"
    else:  # injection
        assert "INC-99999" not in fold(" ".join(texts))
