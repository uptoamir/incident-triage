"""Grounding guardrails (PLAN §9.5). Pure: no I/O, and bad model output is reported, never raised.

Order: G2 allowed ids -> G4 evidence -> G6 count/status -> G5 step sources -> G3 id scan of the text
against the *finally kept* ids -> G7 customer draft -> G8 facts from the DB -> G9 specifics (warn only).
Every model-written string that reaches the answer goes through one sanitizer, so the invariant holds
by construction: every incident id in model-written text is one of the cited ones.
G1 (structure) happens before this, when the model's JSON is parsed into AssistLLMOutput.
"""

import re
import unicodedata
from collections.abc import Iterable
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

# Lookalike dashes become "-" and invisible characters go away before anything is scanned,
# so "INC‑99999" (non-breaking hyphen) can't slip past the id scan.
_FOLD = {
    **dict.fromkeys(map(ord, "‐‑‒–—―−﹘﹣－"), "-"),
    **dict.fromkeys(map(ord, "​‌‍⁠﻿"), None),
}
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})
_EDGE_PUNCT = " .,;:!?\"'()[]"
_ID_CHARS = re.compile(r"[^A-Za-z0-9._:-]")
_SENTINEL = "\x00"
_SPECIFICS = [
    re.compile(r"\b[A-Z]{2,}-\d+\b"),  # error codes like ERR-5003 (incident ids are filtered out below)
    re.compile(r"\bv?\d+\.\d+\.\d+\b"),  # versions like 2.14.0
    re.compile(r"\b\d+(?:\.\d+)?\s?(?:ms|s|%|gb|mb|mib|minutes?|hours?)(?![a-z])", re.IGNORECASE),
]


@dataclass
class GuardrailReport:
    mode: str
    dropped: list[dict] = field(default_factory=list)  # audit trail of removed ids, never model prose
    unverified_evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unsupported_specifics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def fold(text: str) -> str:
    return unicodedata.normalize("NFKC", text).translate(_FOLD)


def _norm(text: str) -> str:
    return " ".join(fold(text).translate(_QUOTES).casefold().split())


def verify_quote(quote: str, field_name: str, record: dict) -> bool:
    """A quote counts only if it names an allowed field, has 3+ words, and is really in that field."""
    if field_name not in EVIDENCE_FIELDS:
        return False
    q = _norm(quote).strip(_EDGE_PUNCT)
    return len(q.split()) >= MIN_QUOTE_WORDS and q in _norm(record[field_name])


class _IdScanner:
    """Finds incident ids in model-written text: the configured pattern, plus the literal id of
    every retrieved incident, so ids of any shape are caught, not only the ones the pattern knows."""

    def __init__(self, id_re: re.Pattern, known_ids: Iterable[str]):
        self.id_re = id_re
        literal = sorted(set(known_ids), key=len, reverse=True)
        alternatives = "|".join(rf"(?<![A-Za-z0-9]){re.escape(k)}(?![A-Za-z0-9])" for k in literal)
        self.literal_re = re.compile(alternatives, re.IGNORECASE) if literal else None

    def find(self, text: str) -> list[str]:
        text = fold(text)
        found = [m.group(0) for m in self.id_re.finditer(text)]  # finditer: fine even if a pattern has groups
        if self.literal_re:
            found += [m.group(0) for m in self.literal_re.finditer(text)]
        return found

    def foreign(self, text: str, allowed: set[str]) -> bool:
        return any(i.upper() not in allowed for i in self.find(text))

    def replace(self, text: str, allowed: set[str], replacement: str) -> str:
        """allowed holds upper-cased ids that may stay; every other id becomes the replacement."""

        def sub(m: re.Match) -> str:
            return m.group(0) if m.group(0).upper() in allowed else replacement

        text = self.id_re.sub(sub, fold(text))
        return self.literal_re.sub(sub, text) if self.literal_re else text


def _resolver(candidates: dict[str, dict]):
    """Exact id first. Case-insensitive only when unambiguous (ingest allows ids that differ only by case)."""
    by_upper: dict[str, list[str]] = {}
    for cid in candidates:
        by_upper.setdefault(cid.upper(), []).append(cid)

    def resolve(raw: str) -> tuple[str | None, str]:
        raw = fold(raw).strip()
        if raw in candidates:
            return raw, ""
        matches = by_upper.get(raw.upper(), [])
        if len(matches) == 1:
            return matches[0], ""
        return None, "ambiguous_id" if matches else "not_retrieved"

    return resolve


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
    known_ids: Iterable[str] = (),
) -> tuple[dict, GuardrailReport]:
    """candidates: the records the model saw. known_ids: every id search returned (for the literal scan)."""
    report = GuardrailReport(mode=mode)
    ids = _IdScanner(re.compile(id_pattern), [*candidates, *known_ids])
    resolve = _resolver(candidates)

    # G2: only incidents the model was shown, matched exactly (never fuzzy), no duplicates
    picked, seen = [], set()
    for n, rel in enumerate(out.relevant_incidents, start=1):
        cid, reason = resolve(rel.incident_id)
        if cid is None:
            safe_id = _ID_CHARS.sub("", fold(rel.incident_id))[:64] or "?"  # id characters only
            report.dropped.append({"id": safe_id, "reason": reason})
        elif cid in seen:
            report.warnings.append(f"incident {n}: duplicate of {cid}, removed")
        else:
            seen.add(cid)
            picked.append((cid, rel))

    # G4: each incident needs at least one verified quote from its own record
    kept = []
    for cid, rel in picked:
        if len(rel.evidence) > MAX_QUOTES:
            report.warnings.append(f"{cid}: only the first {MAX_QUOTES} quotes were checked")
        checked = [
            {
                "field": e.field if e.field in EVIDENCE_FIELDS else "unknown",
                "quote": e.quote,
                "verified": verify_quote(e.quote, e.field, candidates[cid]),
            }
            for e in rel.evidence[:MAX_QUOTES]
        ]
        verified = [e for e in checked if e["verified"]]
        if not verified:
            report.unverified_evidence.append(cid)
            if mode == "strict":
                report.dropped.append({"id": cid, "reason": "evidence_not_verified"})
                continue
        # strict: only verified quotes leave the server; lenient: all of them, flagged
        kept.append((cid, rel, verified if mode == "strict" else checked))

    # G6: cap, then the server decides the status. The model's own flag can only make it stricter.
    if len(kept) > MAX_INCIDENTS:
        report.warnings.append(f"kept the first {MAX_INCIDENTS} of {len(kept)} incidents")
        kept = kept[:MAX_INCIDENTS]
    questions = [q.strip() for q in out.clarifying_questions if q.strip()][:MAX_QUESTIONS]
    if out.insufficient_context or not kept:
        if out.insufficient_context and kept:
            report.warnings.append("the model said nothing is relevant, so its picks were not used")
        # nothing is cited, so no id may appear in the questions
        questions = [ids.replace(q, set(), REMOVED) for q in questions]
        return _insufficient(questions or list(default_questions)), report
    kept_ids = [cid for cid, _, _ in kept]
    allowed = {cid.upper() for cid in kept_ids}

    # G5: sourced steps keep only kept sources; at most 2 general (unsourced) steps
    steps, general = [], 0
    for n, s in enumerate(out.next_steps, start=1):
        text = s.step.strip()
        if not text:
            continue
        if s.source_ids:
            sources = []
            for raw in s.source_ids:
                cid, _ = resolve(raw)
                if cid and cid.upper() in allowed and cid not in sources:
                    sources.append(cid)
            if not sources:
                report.warnings.append(f"step {n}: dropped, none of its sources were kept")
                continue
            steps.append((n, {"step": text, "source_ids": sources, "kind": "from_incidents"}))
        elif general < MAX_GENERAL_STEPS:
            general += 1
            steps.append((n, {"step": text, "source_ids": [], "kind": "general"}))
        else:
            report.warnings.append(f"step {n}: dropped, more than {MAX_GENERAL_STEPS} general steps")

    # G3: free text may only mention incidents that are in the final answer
    relevant = []
    for cid, rel, evidence in kept:
        why = rel.why_relevant.strip()
        if ids.foreign(why, allowed):
            report.warnings.append(f"{cid}: removed a reference to an incident that isn't in the answer")
        rec = candidates[cid]  # G8: facts come from the stored record, not from the model
        relevant.append(
            {
                "id": cid,
                "title": rec["title"],
                "service": rec["service"],
                "environment": rec["environment"],
                "severity": rec["severity"],
                "created_at": rec["created_at"],
                "why_relevant": ids.replace(why, allowed, REMOVED),
                "evidence": [{**e, "quote": ids.replace(e["quote"], allowed, REMOVED)} for e in evidence],
            }
        )
    clean_steps = []
    for n, st in steps:
        if ids.foreign(st["step"], allowed):
            report.warnings.append(f"step {n}: dropped, it names an incident that isn't in the answer")
        else:
            clean_steps.append({**st, "step": fold(st["step"])})
    if len(clean_steps) > MAX_STEPS:
        report.warnings.append(f"kept the first {MAX_STEPS} steps")
        clean_steps = clean_steps[:MAX_STEPS]
    if not clean_steps:
        report.warnings.append("no grounded steps left, so the fallback checklist was used")
        clean_steps = [{"step": s, "source_ids": [], "kind": "general"} for s in FALLBACK_STEPS]

    # G7: the customer draft never contains internal ids, kept or not
    draft, removed = _clean_draft(out.customer_draft, ids)
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
    report.unsupported_specifics = _unsupported(texts, sources, ids, candidates, kept_ids)

    return {
        "status": "ok" if len(kept_ids) >= 3 else "partial",
        "relevant_incidents": relevant,
        "next_steps": clean_steps,
        "customer_draft": {"text": draft, "based_on": kept_ids, "requires_human_review": True},
        "clarifying_questions": [ids.replace(q, allowed, REMOVED) for q in questions],
        "citations": kept_ids,
    }, report


def _clean_draft(text: str, ids: _IdScanner) -> tuple[str, int]:
    removed = len(ids.find(text))
    marked = ids.replace(text, set(), _SENTINEL)
    marked = re.sub(r"\s*[\[(]\s*" + _SENTINEL + r"\s*[\])]", "", marked)  # "(INC-1)" or "[INC-1]" just goes
    return " ".join(marked.replace(_SENTINEL, "a past incident").split()), removed


def _unsupported(texts, sources, ids: _IdScanner, candidates, kept_ids) -> list[str]:
    haystack = _norm(" ".join(sources))
    found = set()
    for text in texts:
        for pattern in _SPECIFICS:
            for m in pattern.finditer(fold(text)):
                token = m.group(0)
                if not ids.find(token) and _norm(token) not in haystack:
                    found.add(token)
    kept_services = {candidates[c]["service"] for c in kept_ids}
    for service in {r["service"] for r in candidates.values()} - kept_services:
        if any(service in t for t in texts) and service not in haystack:
            found.add(service)
    return sorted(found)
