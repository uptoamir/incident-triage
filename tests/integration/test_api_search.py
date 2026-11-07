from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _ingest(client) -> dict:
    r = client.post("/ingest")
    assert r.status_code == 200, r.text
    return r.json()


def test_it1_ingest_twice_then_search_then_fetch(client):
    assert _ingest(client)["ingested"] == 12
    assert _ingest(client)["skipped"] == 12
    body = client.get("/search", params={"q": "connection pool exhausted", "limit": 5}).json()
    assert body["match_mode"] == "all"
    assert body["results"][0]["id"] in {"INC-10001", "INC-10002", "INC-10003"}
    assert body["total"] >= len(body["results"]) > 0
    full = client.get(f"/incidents/{body['results'][0]['id']}").json()
    assert {"title", "description", "resolution_summary", "tags", "ingested_at", "updated_at"} <= full.keys()


def test_auto_falls_back_to_any_word_and_says_so(client):
    _ingest(client)
    body = client.get("/search", params={"q": "certificate quokka"}).json()  # nothing has both words
    assert body["match_mode"] == "any"
    assert body["total"] >= 2


def test_filters_case_and_duplicate_tags(client):
    _ingest(client)
    params = [("q", "timeout"), ("environment", "PROD"), ("tags", "database"), ("tags", "database")]
    assert [h["id"] for h in client.get("/search", params=params).json()["results"]] == ["INC-10001"]
    csv = client.get("/search", params={"q": "certificate", "tags": "tls,certificate"}).json()
    assert {h["id"] for h in csv["results"]} == {"INC-10004", "INC-10005"}


def test_no_searchable_words_is_200_with_a_note(client):
    body = client.get("/search", params={"q": "the and ??"}).json()
    assert body["total"] == 0 and body["terms"] == [] and body["notes"]


def test_hostile_query_is_200_not_500(client):
    _ingest(client)
    assert client.get("/search", params={"q": 'timeout" OR title:x* NEAR(a b) ^c'}).status_code == 200


def test_validation_errors_use_the_envelope(client):
    bad_enum = client.get("/search", params={"q": "x", "severity": "urgent"})
    assert bad_enum.status_code == 422 and bad_enum.json()["error"]["code"] == "validation_error"
    typo = client.get("/search", params={"q": "x", "env": "prod"})
    assert typo.status_code == 422 and typo.json()["error"]["code"] == "unknown_query_parameter"
    assert client.get("/search", params={"q": "x", "limit": 51}).status_code == 422
    assert client.get("/search").status_code == 422  # q is required


def test_incident_not_found_and_bad_id(client):
    missing = client.get("/incidents/INC-99999")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "incident_not_found"
    bad = client.get("/incidents/bad id!")
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_incident_id"


def test_missing_data_file_is_503_with_the_fix(tmp_path):
    s = Settings(_env_file=None, db_path=str(tmp_path / "x.db"), data_path=str(tmp_path / "nope.json"))
    with TestClient(create_app(s)) as c:
        r = c.post("/ingest")
    err = r.json()["error"]
    assert r.status_code == 503 and err["code"] == "data_source_error"
    assert any("make data" in hint for hint in err["how_to_fix"])


def test_health_reports_db_count_and_fts5(client):
    _ingest(client)
    health = client.get("/health").json()
    assert (health["db"], health["incident_count"], health["fts5"]) == ("ok", 12, True)
