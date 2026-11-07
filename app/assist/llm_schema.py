"""What the model must return (PLAN §9.4).

This is the provider-facing shape only: every field required, no defaults, no length keywords,
so it works as an OpenAI strict JSON schema. Counts and lengths are capped by the guardrails,
never by validation, so going over a limit never costs a repair call.
"""

from pydantic import BaseModel, ConfigDict


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceOut(_Strict):
    field: str
    quote: str


class RelevantOut(_Strict):
    incident_id: str
    why_relevant: str
    evidence: list[EvidenceOut]


class StepOut(_Strict):
    step: str
    source_ids: list[str]


class AssistLLMOutput(_Strict):
    insufficient_context: bool
    relevant_incidents: list[RelevantOut]
    next_steps: list[StepOut]
    customer_draft: str
    clarifying_questions: list[str]


def _strip_titles(node):
    # pydantic adds "title": "<Name>" annotations; drop them, but never a property named title
    if isinstance(node, dict):
        return {k: _strip_titles(v) for k, v in node.items() if not (k == "title" and isinstance(v, str))}
    if isinstance(node, list):
        return [_strip_titles(v) for v in node]
    return node


# generated once from the models above, so the prompt's schema and our parser can't disagree
ASSIST_SCHEMA = _strip_titles(AssistLLMOutput.model_json_schema())
