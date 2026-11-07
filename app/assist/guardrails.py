"""Grounding guardrails (PLAN §9.5). Pure: no I/O, and bad model output is reported, never raised.

Order: G2 allowed ids -> G4 evidence -> G6 count/status -> G5 step sources -> G3 id scan of the text
against the *finally kept* ids -> G7 customer draft -> G8 facts from the DB -> G9 specifics (warn only).
G1 (structure) happens before this, when the model's JSON is parsed into AssistLLMOutput.
"""

import re
import unicodedata
from dataclasses import asdict, dataclass, field

from app.assist.llm_schema import AssistLLMOutput

MAX_INCIDENTS = 5
MAX_QUOTES = 2
MAX_STEPS = 7
MAX_GENERAL_STEPS = 2
MAX_QUESTIONS = 4
MAX_DRAFT_CHARS = 1200
MIN_QUOTE_WORDS = 3
EVIDENCE_FIELDS = ("title", "description", "resolution_summary")
REMOVED = "[reference removed]"
FALLBACK_STEPS = [
    "Confirm the scope and start time: error rate, affected users, first occurrence.",
    "Check recent deploys and config changes around the start time.",
]
FALLBACK_DRAFT = (
    "Thanks for reporting this. Our team is looking into it now, and we'll share an update by "
    "[time of next update]."
)

_TYPOGRAPHY = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"})
_EDGE_PUNCT = " .,;:!?\"'()[]"
_SPECIFICS = [
    re.compile(r"\b[A-Z]{2,}-\d+\b"),  # error codes like ERR-5003 (incident ids are filtered out below)
    re.compile(r"\bv?\d+\.\d+\.\d+\b"),  # versions like 2.14.0
    re.compile(r"\b\d+(?:\.\d+)?\s?(?:ms|s|%|gb|mb|mib|minutes?|hours?)(?![a-z])", re.IGNORECASE),
]


@dataclass
class GuardrailReport:
    mode: str
    dropped: list[dict] = field(default_factory=list)
    unverified_evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unsupported_specifics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).translate(_TYPOGRAPHY).casefold().split())


def verify_quote(quote: str, field_name: str, record: dict) -> bool:
    """A quote counts only if it names an allowed field, has 3+ words, and is really in that field."""
    if field_name not in EVIDENCE_FIELDS:
        return False
    q = _norm(quote).strip(_EDGE_PUNCT)
    return len(q.split()) >= MIN_QUOTE_WORDS and q in _norm(record[field_name])


def _insufficient(questions: list[str]) -> dict:
    return {
        "status": "insufficient_context",
        "relevant_incidents": [],
        "next_steps": [],
        "customer_draft": None,
        "clarifying_questions": questions,
        "citations": [],
    }


def apply(
    out: AssistLLMOutput,
    candidates: dict[str, dict],
    question: str,
    *,
    mode: str,
    id_pattern: str,
    default_questions: list[str],
) -> tuple[dict, GuardrailReport]:
    report = GuardrailReport(mode=mode)
    id_re = re.compile(id_pattern)
    by_upper = {cid.upper(): cid for cid in candidates}

    # G2: only incidents search actually returned (case-insensitive, never fuzzy), no duplicates
    picked, seen = [], set()
    for rel in out.relevant_incidents:
        cid = by_upper.get(rel.incident_id.strip().upper())
        if cid is None:
            report.dropped.append({"id": rel.incident_id.strip(), "reason": "not_retrieved"})
        elif cid in seen:
            report.warnings.append(f"duplicate {cid} removed")
        else:
            seen.add(cid)
            picked.append((cid, rel))

    # G4: each incident needs at least one verified quote from its own record
    kept = []
    for cid, rel in picked:
        if len(rel.evidence) > MAX_QUOTES:
            report.warnings.append(f"{cid}: only the first {MAX_QUOTES} quotes were checked")
        evidence = [
            {"field": e.field, "quote": e.quote, "verified": verify_quote(e.quote, e.field, candidates[cid])}
            for e in rel.evidence[:MAX_QUOTES]
        ]
        if not any(e["verified"] for e in evidence):
            report.unverified_evidence.append(cid)
            if mode == "strict":
                report.dropped.append({"id": cid, "reason": "evidence_not_verified"})
                continue
        kept.append((cid, rel, evidence))

    # G6: cap, then the server decides the status. The model's own flag can only make it stricter.
    if len(kept) > MAX_INCIDENTS:
        report.warnings.append(f"kept the first {MAX_INCIDENTS} of {len(kept)} incidents")
        kept = kept[:MAX_INCIDENTS]
    questions = [q.strip() for q in out.clarifying_questions if q.strip()][:MAX_QUESTIONS]
    if out.insufficient_context or not kept:
        if out.insufficient_context and kept:
            report.warnings.append("the model said nothing is relevant, so its picks were not used")
        return _insufficient(questions or list(default_questions)), report
    kept_ids = [cid for cid, _, _ in kept]
    kept_upper = {cid.upper() for cid in kept_ids}

    # G5: sourced steps keep only kept sources; at most 2 general (unsourced) steps
    steps, general = [], 0
    for s in out.next_steps:
        text = s.step.strip()
        if not text:
            continue
        if s.source_ids:
            sources = []
            for raw in s.source_ids:
                cid = by_upper.get(raw.strip().upper())
                if cid and cid.upper() in kept_upper and cid not in sources:
                    sources.append(cid)
            if not sources:
                report.warnings.append(f"step dropped, none of its sources were kept: {text[:60]}")
                continue
            steps.append({"step": text, "source_ids": sources, "kind": "from_incidents"})
        elif general < MAX_GENERAL_STEPS:
            general += 1
            steps.append({"step": text, "source_ids": [], "kind": "general"})
        else:
            report.warnings.append(f"extra general step dropped: {text[:60]}")

    # G3: free text may only mention incidents that are in the final answer
    def foreign(text: str) -> bool:
        return any(m.upper() not in kept_upper for m in id_re.findall(text))

    def scrub(text: str) -> str:
        return id_re.sub(lambda m: m.group(0) if m.group(0).upper() in kept_upper else REMOVED, text)

    relevant = []
    for cid, rel, evidence in kept:
        why = rel.why_relevant.strip()
        if foreign(why):
            report.warnings.append(f"{cid}: removed a reference to an incident that isn't in the answer")
            why = scrub(why)
        rec = candidates[cid]  # G8: facts come from the stored record, not from the model
        relevant.append(
            {
                "id": cid,
                "title": rec["title"],
                "service": rec["service"],
                "environment": rec["environment"],
                "severity": rec["severity"],
                "created_at": rec["created_at"],
                "why_relevant": why,
                "evidence": evidence,
            }
        )
    clean_steps = []
    for st in steps:
        if foreign(st["step"]):
            report.warnings.append(
                f"step dropped, it names an incident that isn't in the answer: {st['step'][:60]}"
            )
        else:
            clean_steps.append(st)
    if len(clean_steps) > MAX_STEPS:
        report.warnings.append(f"kept the first {MAX_STEPS} steps")
        clean_steps = clean_steps[:MAX_STEPS]
    if not clean_steps:
        report.warnings.append("no grounded steps left, so the fallback checklist was used")
        clean_steps = [{"step": s, "source_ids": [], "kind": "general"} for s in FALLBACK_STEPS]

    # G7: the customer draft never contains internal ids, kept or not
    draft, removed = _clean_draft(out.customer_draft, id_re)
    if removed:
        report.warnings.append(f"removed {removed} incident id(s) from the customer draft")
    if len(draft) > MAX_DRAFT_CHARS:
        report.warnings.append("customer draft truncated")
        draft = draft[: MAX_DRAFT_CHARS - 1].rsplit(" ", 1)[0] + "…"
    if not draft:
        report.warnings.append("empty customer draft, so the fallback draft was used")
        draft = FALLBACK_DRAFT

    # G9 (warn only): specific values in our text that aren't in the cited records or the question
    texts = [r["why_relevant"] for r in relevant] + [s["step"] for s in clean_steps] + [draft]
    sources = [question] + [
        " ".join((candidates[c]["title"], candidates[c]["description"], candidates[c]["resolution_summary"]))
        for c in kept_ids
    ]
    report.unsupported_specifics = _unsupported(texts, sources, id_re, candidates, kept_ids)

    return {
        "status": "ok" if len(kept_ids) >= 3 else "partial",
        "relevant_incidents": relevant,
        "next_steps": clean_steps,
        "customer_draft": {"text": draft, "based_on": kept_ids, "requires_human_review": True},
        "clarifying_questions": questions,
        "citations": kept_ids,
    }, report


def _clean_draft(text: str, id_re: re.Pattern) -> tuple[str, int]:
    removed = len(id_re.findall(text))
    bracketed = re.compile(
        r"\s*[\[(]\s*(?:" + id_re.pattern.removeprefix("(?i)") + r")\s*[\])]", re.IGNORECASE
    )
    text = bracketed.sub("", text)
    text = id_re.sub("a past incident", text)
    return " ".join(text.split()), removed


def _unsupported(texts, sources, id_re, candidates, kept_ids) -> list[str]:
    haystack = _norm(" ".join(sources))
    found = set()
    for text in texts:
        for pattern in _SPECIFICS:
            for m in pattern.findall(text):
                if not id_re.fullmatch(m) and _norm(m) not in haystack:
                    found.add(m)
    kept_services = {candidates[c]["service"] for c in kept_ids}
    for service in {r["service"] for r in candidates.values()} - kept_services:
        if any(service in t for t in texts) and service not in haystack:
            found.add(service)
    return sorted(found)
