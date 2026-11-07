"""Test doubles. They live only in tests/; nothing at runtime can select them."""

import re

from app.llm.base import LLMResult

_BLOCK = re.compile(r'<incident id="([^"]+)"[^>]*>\ntitle: (.*)\n')


def grounded_answer(user: str, n: int = 3) -> dict:
    """What a well-behaved model returns: cites retrieved incidents, quotes their titles exactly."""
    picks = _BLOCK.findall(user)[:n]
    return {
        "insufficient_context": False,
        "relevant_incidents": [
            {
                "incident_id": cid,
                "why_relevant": f"Similar symptom [{cid}].",
                "evidence": [{"field": "title", "quote": " ".join(title.split()[:5])}],
            }
            for cid, title in picks
        ],
        "next_steps": [
            {"step": f"Apply the fix from [{picks[0][0]}].", "source_ids": [picks[0][0]]},
            {"step": "Confirm when it started.", "source_ids": []},
        ],
        "customer_draft": "We're looking into it and will update you by [time of next update].",
        "clarifying_questions": [],
    }


class FakeLLMClient:
    """Scripted: each call takes the next item (a dict, a callable(user) -> dict, or an exception)."""

    provider = "fake"
    model = "fake-model"

    def __init__(self, *script):
        self.script = list(script)
        self.calls: list[dict] = []

    def describe(self) -> dict:
        return {"provider": self.provider, "model": self.model, "configured": True, "missing": []}

    def complete_json(self, system, user, schema, *, schema_name, timeout_s=None) -> LLMResult:
        self.calls.append({"system": system, "user": user, "schema": schema, "schema_name": schema_name})
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, Exception):
            raise item
        data = item(user) if callable(item) else item
        return LLMResult(
            data=data,
            model=self.model,
            latency_ms=1.0,
            finish_reason="stop",
            usage={"input": 100, "output": 50},
        )
