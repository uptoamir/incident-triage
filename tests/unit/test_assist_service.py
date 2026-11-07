"""ASSIST_DEADLINE_SECONDS is a hard cap, checked with a fake clock.

Defaults: 45 s deadline, 20 s per-try timeout, 1 SDK retry.
"""

import pytest

from app.assist.service import AssistService
from app.ingest.service import IngestService
from app.llm.base import LLMInvalidOutput
from app.observability.trace import Trace
from app.search.db import Database
from app.search.query_builder import SearchFilters
from app.search.repository import SqliteIncidentRepository
from app.search.service import SearchService
from tests.fakes import FakeLLMClient, grounded_answer

QUESTION = "Payroll run timing out with connection pool exhausted errors in prod"


@pytest.fixture
def make_service(tmp_path, settings, fixture_records):
    db = Database(str(tmp_path / "s.db"))
    db.init_schema()
    repo = SqliteIncidentRepository(db)
    IngestService(repo, settings).ingest(fixture_records)

    def make(fake, clock):
        return AssistService(SearchService(repo, settings), repo, fake, settings, clock=clock)

    return make


def _fake_clock(seconds_per_first_call):
    now = {"t": 1000.0}

    def advance(call_number):
        if call_number == 1:
            now["t"] += seconds_per_first_call

    return (lambda: now["t"]), advance


def test_the_repair_call_only_gets_the_time_that_is_left(make_service):
    clock, advance = _fake_clock(40.0)  # the first call (with its SDK retry) burns 40 of the 45 s
    fake = FakeLLMClient({"not": "the schema"}, grounded_answer)
    fake.on_call = advance
    make_service(fake, clock).assist(QUESTION, SearchFilters(), Trace("cid", "POST", "/assist"))
    first, second = fake.calls
    assert (first["timeout_s"], first["max_retries"]) == (20, 1)
    assert second["max_retries"] == 0 and second["timeout_s"] == pytest.approx(5.0)


def test_no_repair_call_when_there_is_no_time_left(make_service):
    clock, advance = _fake_clock(44.0)
    fake = FakeLLMClient({"not": "the schema"}, grounded_answer)
    fake.on_call = advance
    with pytest.raises(LLMInvalidOutput) as exc:
        make_service(fake, clock).assist(QUESTION, SearchFilters(), Trace("cid", "POST", "/assist"))
    assert exc.value.details["reason"] == "deadline" and len(fake.calls) == 1
