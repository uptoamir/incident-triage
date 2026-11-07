"""SearchService.search() is the single search code path: /search and /assist both call it."""

import json
from dataclasses import dataclass, field

from app.config import Settings
from app.search.query_builder import SearchFilters, build
from app.search.repository import IncidentRepository
from app.search.terms import extract

NO_TERMS_NOTE = "q has no searchable words; try a service name, an error message, or a symptom"


@dataclass(frozen=True)
class SearchRequest:
    q: str
    filters: SearchFilters = field(default_factory=SearchFilters)
    match: str = "auto"  # auto: all words first, any word if that finds nothing
    limit: int = 10
    offset: int = 0


@dataclass
class SearchResult:
    total: int
    hits: list[dict]
    terms: list[str]
    match_mode: str
    notes: list[str] = field(default_factory=list)


class SearchService:
    def __init__(self, repo: IncidentRepository, settings: Settings):
        self.repo = repo
        self.settings = settings

    def search(self, req: SearchRequest) -> SearchResult:
        # no character cap here on purpose: that lives in the HTTP models, so a long /assist
        # question is never rejected by search. The term cap bounds the work instead.
        terms = extract(req.q, self.settings.search_max_terms)
        first_mode = "any" if req.match == "any" else "all"
        if not terms:
            return SearchResult(total=0, hits=[], terms=[], match_mode=first_mode, notes=[NO_TERMS_NOTE])
        hits, total = self.repo.search(build(terms, req.filters, first_mode, req.limit, req.offset))
        mode = first_mode
        if req.match == "auto" and total == 0:
            mode = "any"
            hits, total = self.repo.search(build(terms, req.filters, mode, req.limit, req.offset))
        return SearchResult(total=total, hits=[_hit(row) for row in hits], terms=terms, match_mode=mode)


def _hit(row: dict) -> dict:
    snippet = (row.get("snippet") or "").strip() or row["description"][:160]
    return {
        "id": row["id"],
        "title": row["title"],
        "snippet": snippet[:200],
        "score": round(-row["bm25_score"], 3),  # FTS5 bm25: lower is better; flip so higher is better
        "service": row["service"],
        "environment": row["environment"],
        "severity": row["severity"],
        "created_at": row["created_at"],
        "tags": json.loads(row["tags_json"]),
    }
