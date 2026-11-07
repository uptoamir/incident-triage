"""The only module with SQL. A Postgres or OpenSearch adapter would implement the same methods."""

import json
from contextlib import closing
from typing import Protocol

from app.search.db import Database
from app.search.query_builder import CompiledQuery

_COLUMNS = (
    "id, created_at, environment, service, severity, title, description, resolution_summary, "
    "tags_json, content_hash, ingested_at, updated_at"
)
# every column except id and ingested_at: an update keeps the first-seen time
_UPDATABLE = (
    "created_at", "environment", "service", "severity", "title", "description",
    "resolution_summary", "tags_json", "content_hash", "updated_at",
)  # fmt: skip
_UPSERT_SQL = (
    f"INSERT INTO incidents ({_COLUMNS}) VALUES ({', '.join('?' * 12)}) "
    "ON CONFLICT(id) DO UPDATE SET " + ", ".join(f"{col} = excluded.{col}" for col in _UPDATABLE)
)


class IncidentRepository(Protocol):
    def upsert_many(self, records: list[dict], now: str) -> dict: ...
    def get(self, incident_id: str) -> dict | None: ...
    def get_many(self, ids: list[str]) -> dict[str, dict]: ...
    def search(self, query: CompiledQuery) -> tuple[list[dict], int]: ...
    def count_all(self) -> int: ...


class SqliteIncidentRepository:
    def __init__(self, db: Database):
        self.db = db

    def upsert_many(self, records: list[dict], now: str) -> dict:
        """records are canonical dicts plus content_hash. One transaction, all or nothing."""
        counts = {"ingested": 0, "updated": 0, "skipped": 0}
        with closing(self.db.connect()) as conn:
            # IMMEDIATE takes the write lock before we read the hashes, so two concurrent
            # ingests run one after the other instead of failing with "database is locked"
            conn.execute("BEGIN IMMEDIATE")
            try:
                stored = self._stored_hashes(conn, [r["id"] for r in records])
                for r in records:
                    old = stored.get(r["id"])
                    if old == r["content_hash"]:
                        counts["skipped"] += 1
                        continue
                    self._write(conn, r, now)
                    counts["ingested" if old is None else "updated"] += 1
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        return counts

    @staticmethod
    def _stored_hashes(conn, ids: list[str]) -> dict[str, str]:
        stored: dict[str, str] = {}
        for start in range(0, len(ids), 500):  # stay well under SQLite's variable limit
            chunk = ids[start : start + 500]
            marks = ", ".join("?" for _ in chunk)
            rows = conn.execute(f"SELECT id, content_hash FROM incidents WHERE id IN ({marks})", chunk)
            stored.update({row["id"]: row["content_hash"] for row in rows})
        return stored

    @staticmethod
    def _write(conn, r: dict, now: str) -> None:
        # Not INSERT OR REPLACE: it can't tell "updated" from "unchanged" and would reset ingested_at.
        conn.execute(
            _UPSERT_SQL,
            (
                r["id"], r["created_at"], r["environment"], r["service"], r["severity"], r["title"],
                r["description"], r["resolution_summary"], json.dumps(r["tags"]), r["content_hash"], now, now,
            ),
        )  # fmt: skip
        conn.execute("DELETE FROM incident_tags WHERE incident_id = ?", (r["id"],))
        conn.executemany(
            "INSERT INTO incident_tags (incident_id, tag) VALUES (?, ?)", [(r["id"], t) for t in r["tags"]]
        )
        conn.execute("DELETE FROM incidents_fts WHERE incident_id = ?", (r["id"],))
        conn.execute(
            "INSERT INTO incidents_fts (incident_id, title, description, resolution_summary, tags) "
            "VALUES (?, ?, ?, ?, ?)",
            (r["id"], r["title"], r["description"], r["resolution_summary"], " ".join(r["tags"])),
        )

    def get(self, incident_id: str) -> dict | None:
        with closing(self.db.connect()) as conn:
            row = conn.execute(f"SELECT {_COLUMNS} FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        return _record(row) if row else None

    def get_many(self, ids: list[str]) -> dict[str, dict]:
        if not ids:
            return {}
        marks = ", ".join("?" for _ in ids)
        with closing(self.db.connect()) as conn:
            rows = conn.execute(f"SELECT {_COLUMNS} FROM incidents WHERE id IN ({marks})", ids).fetchall()
        return {row["id"]: _record(row) for row in rows}

    def search(self, query: CompiledQuery) -> tuple[list[dict], int]:
        with closing(self.db.connect()) as conn:
            # One read transaction for both statements: in WAL mode they then see the same
            # snapshot, so total can't disagree with the rows if an ingest commits in between.
            conn.execute("BEGIN")
            try:
                rows = conn.execute(*query.results_sql()).fetchall()
                total = conn.execute(*query.count_sql()).fetchone()[0]
            finally:
                conn.execute("COMMIT")
        return [dict(row) for row in rows], total

    def count_all(self) -> int:
        with closing(self.db.connect()) as conn:
            return conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]


def _record(row) -> dict:
    out = {key: row[key] for key in row.keys() if key not in ("tags_json", "content_hash")}
    out["tags"] = json.loads(row["tags_json"])
    return out
