"""Terms + filters -> SQL and parameters. Pure, no I/O (PLAN §7.2).

User values only ever go into bound parameters. The SQL text is built from fixed fragments
and placeholder counts, never from anything the user typed.
"""

from dataclasses import dataclass

# bm25 weights, in FTS column order: incident_id (unindexed), title, description, resolution, tags
_BM25 = "bm25(incidents_fts, 0.0, 8.0, 2.0, 3.0, 5.0)"
_FROM = "FROM incidents_fts JOIN incidents i ON i.id = incidents_fts.incident_id"
_SELECT = (
    "SELECT i.id, i.title, i.environment, i.service, i.severity, i.created_at, i.tags_json, i.description, "
    "snippet(incidents_fts, -1, '**', '**', '…', 16) AS snippet, " + _BM25 + " AS bm25_score "
)


@dataclass(frozen=True)
class SearchFilters:
    environment: str | None = None
    service: str | None = None
    severity: str | None = None
    tags: tuple[str, ...] = ()

    def summary(self) -> dict:
        """Only the filters that were actually set, for responses and logs."""
        out = {
            k: v
            for k, v in (
                ("environment", self.environment),
                ("service", self.service),
                ("severity", self.severity),
            )
            if v
        }
        if self.tags:
            out["tags"] = sorted(set(self.tags))
        return out


@dataclass(frozen=True)
class CompiledQuery:
    match: str
    where: str
    params: tuple
    limit: int
    offset: int

    def results_sql(self) -> tuple[str, tuple]:
        sql = (
            f"{_SELECT}{_FROM} WHERE {self.where} "
            "ORDER BY bm25_score ASC, i.created_at DESC, i.id ASC LIMIT ? OFFSET ?"
        )
        return sql, (*self.params, self.limit, self.offset)

    def count_sql(self) -> tuple[str, tuple]:
        return f"SELECT COUNT(*) {_FROM} WHERE {self.where}", self.params


def fts_literal(term: str) -> str:
    """An FTS5 string literal. Terms are already \\w+ only; doubling quotes is defence in depth."""
    return '"' + term.replace('"', '""') + '"'


def build(terms: list[str], filters: SearchFilters, mode: str, limit: int, offset: int) -> CompiledQuery:
    if not terms:
        raise ValueError("build() needs at least one term; callers handle the no-terms case")
    if mode not in ("all", "any"):
        raise ValueError(f"mode must be 'all' or 'any', got {mode!r}")
    match = (" AND " if mode == "all" else " OR ").join(fts_literal(t) for t in terms)

    clauses = ["incidents_fts MATCH ?"]
    params: list = [match]
    for column in ("environment", "service", "severity"):  # fixed column names
        value = getattr(filters, column)
        if value:
            clauses.append(f"i.{column} = ?")
            params.append(value)
    tags = sorted(set(filters.tags))  # dedupe first: tags=db&tags=db must not ask for 2 distinct tags
    if tags:
        marks = ", ".join("?" for _ in tags)
        clauses.append(
            f"i.id IN (SELECT incident_id FROM incident_tags WHERE tag IN ({marks}) "
            "GROUP BY incident_id HAVING COUNT(DISTINCT tag) = ?)"
        )
        params.extend(tags)
        params.append(len(tags))
    return CompiledQuery(
        match=match, where=" AND ".join(clauses), params=tuple(params), limit=limit, offset=offset
    )
