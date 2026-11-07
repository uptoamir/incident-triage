import re
from contextlib import closing

import pytest

from app.search.db import Database
from app.search.query_builder import SearchFilters, build
from app.search.terms import extract

HOSTILE = [
    'timeout" OR title:x* NEAR(a b) ^c -y',
    'payroll"; DROP TABLE incidents; --',
    "NOT near AND",
    "über café São",
    "ERR-5003 v2.14.0",
]


@pytest.fixture
def db(tmp_path):
    database = Database(str(tmp_path / "q.db"))
    database.init_schema()
    return database


def test_qb1_fts_operators_in_user_input_never_reach_match():
    cq = build(extract(HOSTILE[0], 16), SearchFilters(), "any", 10, 0)
    assert all(re.fullmatch(r'"\w+"', part) for part in cq.match.split(" OR "))
    assert not re.search(r"[*:^()+\-]", cq.match)


@pytest.mark.parametrize("text", HOSTILE)
def test_qb1_hostile_input_builds_sql_that_real_fts5_accepts(db, text):
    cq = build(extract(text, 16), SearchFilters(), "any", 10, 0)
    with closing(db.connect()) as conn:
        conn.execute(*cq.results_sql()).fetchall()
        conn.execute(*cq.count_sql()).fetchone()


def test_qb2_stopwords_short_tokens_dupes_and_cap():
    assert extract("why is the payroll job down?", 16) == ["payroll", "job", "down"]
    assert extract("Timeout timeout TIMEOUT", 16) == ["timeout"]
    assert len(extract(" ".join(f"word{i}" for i in range(30)), 16)) == 16


def test_qb3_filter_values_only_ever_appear_in_params():
    evil = "prod' OR 1=1 --"
    cq = build(
        ["payroll"], SearchFilters(environment=evil, service=evil, severity=evil, tags=(evil,)), "all", 10, 0
    )
    sql, params = cq.results_sql()
    assert evil not in sql
    assert params.count(evil) == 4


def test_qb4_duplicate_tags_are_removed_before_counting():
    cq = build(["timeout"], SearchFilters(tags=("db", "db")), "any", 10, 0)
    assert cq.params[-1] == 1  # HAVING COUNT(DISTINCT tag) = 1, not 2


def test_qb5_all_and_any_modes_share_one_where_clause():
    filters = SearchFilters(environment="prod")
    assert build(["a1", "b2"], filters, "all", 10, 0).match == '"a1" AND "b2"'
    cq = build(["a1", "b2"], filters, "any", 10, 0)
    assert cq.match == '"a1" OR "b2"'
    results_sql, results_params = cq.results_sql()
    count_sql, count_params = cq.count_sql()
    assert cq.where in results_sql and cq.where in count_sql
    assert results_params[: len(count_params)] == count_params


def test_qb6_text_with_no_searchable_words_gives_no_terms():
    assert extract("?? !! the and", 16) == []
    with pytest.raises(ValueError):
        build([], SearchFilters(), "any", 10, 0)
