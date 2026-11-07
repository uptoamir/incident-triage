import json
from pathlib import Path

from app.domain.models import Incident
from scripts.generate_incidents import INJECTION_TEXT, UNRESOLVED, dump, generate

ROOT = Path(__file__).resolve().parents[2]


def test_dg1_same_seed_gives_byte_identical_output_matching_the_committed_files():
    first, golden_first = generate(42, 300)
    second, golden_second = generate(42, 300)
    assert dump(first) == dump(second)
    assert dump(golden_first) == dump(golden_second)
    assert dump(first) == (ROOT / "data/incidents.json").read_text(encoding="utf-8")
    assert dump(golden_first) == (ROOT / "data/golden.json").read_text(encoding="utf-8")


def test_environment_mix_is_exactly_40_20_20_20():
    incidents, _ = generate(42, 300)
    counts = {env: sum(i["environment"] == env for i in incidents) for env in ("prod", "stage", "qa", "dev")}
    assert counts == {"prod": 120, "stage": 60, "qa": 60, "dev": 60}


def test_different_seed_gives_different_data():
    assert dump(generate(7, 300)[0]) != dump(generate(42, 300)[0])


def test_dataset_shape_and_planted_edge_cases():
    incidents, golden = generate(42, 300)
    ids = [i["id"] for i in incidents]
    assert len(incidents) == 300 and len(set(ids)) == 300
    assert all(Incident.model_validate(i).to_record() == i for i in incidents)  # already canonical
    assert any(i["resolution_summary"] == UNRESOLVED for i in incidents)
    assert any(len(i["description"]) > 1500 for i in incidents)
    assert sum(INJECTION_TEXT in i["description"] for i in incidents) == 1
    known = set(ids)
    matches = [g for g in golden if g["kind"] == "match"]
    assert len(matches) == 5
    assert all(len(g["expected_ids"]) == 4 and set(g["expected_ids"]) <= known for g in matches)
    assert {g["kind"] for g in golden} == {"match", "no_match", "injection"}


def test_test_fixture_is_valid_and_canonical():
    records = json.loads((ROOT / "tests/fixtures/incidents_small.json").read_text(encoding="utf-8"))
    assert len(records) == 12
    assert len({r["id"] for r in records}) == 12
    for r in records:
        Incident.model_validate(r)
