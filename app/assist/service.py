"""/assist orchestration (PLAN §9.1): tool:search -> gate -> context -> LLM (+1 repair) -> guardrails."""

import hashlib
import logging
import time

from pydantic import ValidationError

from app.assist import guardrails
from app.assist.context import Context, build_context
from app.assist.llm_schema import ASSIST_SCHEMA, AssistLLMOutput
from app.assist.prompts import PROMPT_VERSION, REPAIR_NOTE, SYSTEM_PROMPT, build_user_message
from app.config import Settings
from app.llm.base import LLMClient, LLMError, LLMInvalidOutput
from app.observability.trace import Trace
from app.search.query_builder import SearchFilters
from app.search.repository import IncidentRepository
from app.search.service import SearchRequest, SearchService

log = logging.getLogger("app.assist")


def default_questions(filters: dict) -> list[str]:
    """Clarifying questions tailored to what's missing (PLAN §9.6)."""
    questions = []
    if "service" not in filters:
        questions.append("Which service is affected?")
    if "environment" not in filters:
        questions.append("Which environment: prod, stage, qa or dev?")
    questions.append("What exact error message or code do you see?")
    questions.append("When did it start, and was there a deploy or config change just before?")
    return questions[:4]


class AssistService:
    def __init__(self, search: SearchService, repo: IncidentRepository, llm: LLMClient, settings: Settings):
        self.search = search
        self.repo = repo
        self.llm = llm
        self.settings = settings

    def assist(self, question: str, filters: SearchFilters, trace: Trace) -> dict:
        applied = filters.summary()
        with trace.step(
            "assist.validate",
            {
                "question_chars": len(question),
                "question_sha": hashlib.sha256(question.encode()).hexdigest()[:12],
            },
        ) as s:
            s.output = {"ok": True, "filters": applied}

        # the exact same call GET /search?q=<question>&match=any&limit=ASSIST_CANDIDATES makes
        req = SearchRequest(q=question, filters=filters, match="any", limit=self.settings.assist_candidates)
        with trace.step("tool:search", {"filters": applied, "match": "any", "limit": req.limit}) as s:
            result = self.search.search(req)
            s.input["terms"] = result.terms
            s.output = {"total_hits": result.total, "top": [[h["id"], h["score"]] for h in result.hits]}
        retrieval = {
            "terms": result.terms,
            "match_mode": result.match_mode,
            "filters": applied,
            "total_hits": result.total,
            "candidate_ids": [h["id"] for h in result.hits],
        }

        if not result.hits:  # nothing to ground an answer on: don't call the LLM at all
            reason = "no_searchable_terms" if not result.terms else "no_hits"
            with trace.step("assist.gate") as s:
                s.output = {"llm_skipped": True, "reason": reason}
            return self._finish(trace, self._nothing_found(applied, reason, retrieval))

        records = self.repo.get_many(retrieval["candidate_ids"])
        ordered = [records[i] for i in retrieval["candidate_ids"] if i in records]
        with trace.step("context.build", {"candidate_ids": retrieval["candidate_ids"]}) as s:
            ctx = build_context(ordered, self.settings.assist_max_context_chars)
            s.output = {
                "chars": len(ctx.text),
                "budget": self.settings.assist_max_context_chars,
                "included": len(ctx.included_ids),
                "dropped": ctx.dropped_ids,
                "truncated": ctx.truncated,
            }

        try:
            output, llm_meta = self._ask_llm(question, applied, ctx, trace)
        except LLMError as exc:
            # search still worked, so on-call can carry on by hand
            exc.details = {
                **exc.details,
                "retrieved": [{"id": r["id"], "title": r["title"]} for r in ordered],
            }
            raise

        candidates = {i: records[i] for i in ctx.included_ids}  # only what the model actually saw
        with trace.step(
            "guardrail:validate", {"proposed_ids": [r.incident_id for r in output.relevant_incidents]}
        ) as s:
            answer, report = guardrails.apply(
                output,
                candidates,
                question,
                mode=self.settings.guardrail_mode,
                id_pattern=self.settings.incident_id_pattern,
                default_questions=default_questions(applied),
            )
            s.output = {
                "kept": answer["citations"],
                **{k: v for k, v in report.to_dict().items() if k != "mode"},
            }
            if report.dropped or report.warnings or report.unsupported_specifics:
                s.level = logging.WARNING

        return self._finish(
            trace,
            {
                "status": answer["status"],
                "message": _message(answer),
                **{k: v for k, v in answer.items() if k != "status"},
                "guardrails": report.to_dict(),
                "retrieval": retrieval,
                "llm": llm_meta,
            },
        )

    def _ask_llm(
        self, question: str, applied: dict, ctx: Context, trace: Trace
    ) -> tuple[AssistLLMOutput, dict]:
        deadline = time.monotonic() + self.settings.assist_deadline_seconds
        user = build_user_message(question, applied, ctx.text)
        meta = {
            "provider": self.llm.provider,
            "model": self.llm.model,
            "prompt_version": PROMPT_VERSION,
            "attempts": 0,
            "latency_ms": 0.0,
            "tokens": {"input": 0, "output": 0},
        }
        problem = ""
        for attempt in (1, 2):
            if attempt == 2:
                if deadline - time.monotonic() < self.settings.llm_timeout_seconds:
                    raise LLMInvalidOutput(
                        "The model's answer couldn't be used, and there's no time left to ask again.",
                        how_to_fix=["retry"],
                        details={"reason": "schema", "problem": problem},
                    )
                user += REPAIR_NOTE.format(problem=problem)
            meta["attempts"] = attempt
            with trace.step(
                "llm:call",
                {
                    "attempt": attempt,
                    "provider": self.llm.provider,
                    "model": self.llm.model,
                    "prompt_version": PROMPT_VERSION,
                    "json_mode": self.settings.llm_json_mode,
                    "prompt_chars": len(SYSTEM_PROMPT) + len(user),
                },
            ) as s:
                try:
                    result = self.llm.complete_json(
                        SYSTEM_PROMPT, user, ASSIST_SCHEMA, schema_name="assist_output"
                    )
                except LLMInvalidOutput as exc:
                    if exc.details.get("reason") == "truncated" or attempt == 2:
                        raise  # asking again won't help a cut-off answer
                    problem = exc.message
                    s.status, s.output = "invalid", {"problem": problem}
                    continue
                meta["model"] = result.model
                meta["latency_ms"] = round(meta["latency_ms"] + result.latency_ms, 1)
                for k in ("input", "output"):
                    meta["tokens"][k] += result.usage.get(k, 0)
                s.output = {
                    "latency_ms": result.latency_ms,
                    "tokens": result.usage,
                    "finish_reason": result.finish_reason,
                }
                if self.settings.log_llm_payloads:
                    log.info(
                        "llm payload", extra={"event": "llm.payload", "user": user, "reply": result.data}
                    )
                try:
                    return AssistLLMOutput.model_validate(result.data), meta
                except ValidationError as exc:
                    problem = "; ".join(
                        f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:3]
                    )
                    s.status, s.output["problem"] = "invalid", problem
                    if attempt == 2:
                        raise LLMInvalidOutput(
                            "The model's answer didn't match the schema, even after one repair attempt.",
                            how_to_fix=["retry", "or try a different LLM_MODEL"],
                            details={"reason": "schema", "problem": problem},
                        ) from None
        raise AssertionError("unreachable")

    def _nothing_found(self, applied: dict, reason: str, retrieval: dict) -> dict:
        if self.repo.count_all() == 0:
            message = "No incidents are indexed yet. Run POST /ingest first."
        elif reason == "no_searchable_terms":
            message = (
                "The question has no searchable words. Add a service name, an error message or a symptom."
            )
        else:
            message = "No incidents matched this question."
            if applied:
                message += f" Filters applied: {applied}; try relaxing them."
        return {
            "status": "insufficient_context",
            "message": message,
            "relevant_incidents": [],
            "next_steps": [],
            "customer_draft": None,
            "clarifying_questions": default_questions(applied),
            "citations": [],
            "guardrails": None,
            "retrieval": retrieval,
            "llm": None,
        }

    def _finish(self, trace: Trace, response: dict) -> dict:
        with trace.step("assist.selected") as s:
            s.output = {"selected_ids": response["citations"], "status": response["status"]}
        log.info(
            "assist %s: %s",
            response["status"],
            response["citations"],
            extra={
                "event": "assist.completed",
                "steps": [step.name for step in trace.steps],
                "selected_ids": response["citations"],
                "status": response["status"],
            },
        )
        return response


def _message(answer: dict) -> str | None:
    if answer["status"] == "partial":
        n = len(answer["citations"])
        plural = "s" if n > 1 else ""
        return f"Only {n} closely related past incident{plural} found; check the steps before acting."
    if answer["status"] == "insufficient_context":
        return "No sufficiently relevant past incidents were found for this question."
    return None
