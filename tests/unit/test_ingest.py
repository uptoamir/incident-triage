import copy
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from app.ingest.service import IngestService
from app.search.db import Database
from app.search.query_builder import SearchFilters, build
from app.search.repository import SqliteIncidentRepository


@pytest.fixture
def repo(tmp_path):
    db = Database(str(tmp_path / "ingest.db"))
    db.init_schema()
    return SqliteIncidentRepository(db)


@pytest.fixture
def ingest(repo, settings):
    return IngestService(repo, settings)


def _fts_rows(repo) -> int:
    with closing(repo.db.connect()) as conn:
        return conn.execute("SELECT COUNT(*) FROM incidents_fts").fetchone()[0]


def _hits(repo, word) -> int:
    return repo.search(build([word], SearchFilters(), "any", 10, 0))[1]


def _counts(result) -> tuple:
    return result["ingested"], result["updated"], result["skipped"]


def test_in1_ingesting_twice_changes_nothing(ingest, repo, fixture_records):
    assert _counts(ingest.ingest(fixture_records)) == (12, 0, 0)
    assert _counts(ingest.ingest(fixture_records)) == (0, 0, 12)
    assert repo.count_all() == 12 == _fts_rows(repo)


def test_in1_no_body_loads_data_path(ingest):
    result = ingest.ingest(None)
    assert result["source"].startswith("file:")
    assert result["ingested"] == 12


def test_in2_edited_record_is_updated_and_its_old_text_is_gone(ingest, repo, fixture_records):
    ingest.ingest(fixture_records)
    assert _hits(repo, "workers") == 1  # only in INC-10001's original description
    edited = copy.deepcopy(fixture_records)
    edited[0]["description"] = "Completely new words: quokka."
    assert _counts(ingest.ingest(edited)) == (0, 1, 11)
    assert _hits(repo, "quokka") == 1
    assert _hits(repo, "workers") == 0
    assert repo.count_all() == 12 == _fts_rows(repo)


def test_in3_equivalent_input_counts_as_unchanged(ingest, fixture_records):
    ingest.ingest(fixture_records)
    same = copy.deepcopy(fixture_records)
    same[0]["tags"] = [t.upper() for t in reversed(same[0]["tags"])]
    same[1]["created_at"] = same[1]["created_at"].replace("Z", "+00:00")
    assert _counts(ingest.ingest(same)) == (0, 0, 12)


def test_in3_bad_records_are_reported_and_the_rest_still_go_in(ingest, fixture_records):
    batch = [fixture_records[0], {"id": "bad id"}, "not an object", fixture_records[0], fixture_records[1]]
    result = ingest.ingest(batch)
    assert result["ingested"] == 2
    assert result["invalid"] == 3
    reasons = " | ".join(e["reason"] for e in result["errors"])
    assert "duplicate id" in reasons and "not a JSON object" in reasons


class _RacyRepo(SqliteIncidentRepository):
    """Pauses each ingest right after it reads the stored hashes: the exact racy spot.

    A plain ThreadPool test only caught a BEGIN (not IMMEDIATE) mutation in 3 of 5 runs,
    because the threads didn't always overlap. The barrier makes them overlap every time.
    """

    def __init__(self, db, barrier):
        super().__init__(db)
        self.barrier = barrier

    def _stored_hashes(self, conn, ids):
        stored = super()._stored_hashes(conn, ids)
        try:
            self.barrier.wait(timeout=1.0)  # with BEGIN IMMEDIATE the other ingest can't get here yet
        except threading.BrokenBarrierError:
            pass
        return stored


def test_two_ingests_at_once_neither_fails_nor_double_counts(repo, settings, fixture_records):
    racy = IngestService(_RacyRepo(repo.db, threading.Barrier(2)), settings)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(racy.ingest, [fixture_records, fixture_records]))
    assert sorted(r["ingested"] for r in results) == [0, 12]
    assert sorted(r["skipped"] for r in results) == [0, 12]
