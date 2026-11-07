"""Candidate records -> the bounded, delimited context the model sees (PLAN §9.2)."""

from dataclasses import dataclass, field

DESCRIPTION_MAX = 1500
RESOLUTION_MAX = 800
TRUNCATED = "…[truncated]"


@dataclass
class Context:
    text: str
    included_ids: list[str]
    dropped_ids: list[str] = field(default_factory=list)
    truncated: list[str] = field(default_factory=list)  # "INC-00042.description"


def _cut(value: str, limit: int) -> tuple[str, bool]:
    return (value, False) if len(value) <= limit else (value[:limit] + TRUNCATED, True)


def _defang(value: str) -> str:
    # a record can't close its own block and smuggle "instructions" in after it
    return value.replace("</incident", "</ incident").replace("<incident", "< incident")


def _block(rec: dict) -> tuple[str, list[str]]:
    description, cut_d = _cut(rec["description"], DESCRIPTION_MAX)
    resolution, cut_r = _cut(rec["resolution_summary"], RESOLUTION_MAX)
    truncated = [f"{rec['id']}.description"] * cut_d + [f"{rec['id']}.resolution_summary"] * cut_r
    attrs = (
        f'id="{rec["id"]}" service="{rec["service"]}" environment="{rec["environment"]}" '
        f'severity="{rec["severity"]}" created_at="{rec["created_at"]}" tags="{", ".join(rec["tags"])}"'
    )
    body = (
        f"title: {_defang(rec['title'])}\n"
        f"description: {_defang(description)}\n"
        f"resolution_summary: {_defang(resolution)}"
    )
    return f"<incident {attrs}>\n{body}\n</incident>", truncated


def build_context(records: list[dict], max_chars: int) -> Context:
    """records are in search-rank order. Over the budget, the lowest-ranked ones are dropped first."""
    blocks, ids, truncated, used = [], [], [], 0
    dropped = []
    for rec in records:
        block, cut = _block(rec)
        if used + len(block) > max_chars and blocks:
            dropped.append(rec["id"])
            continue
        blocks.append(block)
        ids.append(rec["id"])
        truncated.extend(cut)
        used += len(block) + 2
    return Context(text="\n\n".join(blocks), included_ids=ids, dropped_ids=dropped, truncated=truncated)
