import pytest
from pydantic import ValidationError

from app.domain.models import Incident

BASE = {
    "id": "INC-00001",
    "created_at": "2026-03-14T09:21:00Z",
    "environment": "prod",
    "service": "payroll-engine",
    "severity": "SEV2",
    "title": "t",
    "description": "d",
    "resolution_summary": "r",
    "tags": ["database"],
}


def _incident(**over) -> Incident:
    return Incident.model_validate({**BASE, **over})


def test_tags_are_trimmed_lowercased_deduped_and_sorted():
    assert _incident(tags=[" Timeout", "database", "DATABASE "]).tags == ["database", "timeout"]


def test_equivalent_timestamps_give_the_same_canonical_value():
    z = _incident(created_at="2026-03-14T09:21:00Z").to_record()["created_at"]
    offset = _incident(created_at="2026-03-14T11:21:00+02:00").to_record()["created_at"]
    assert z == offset == "2026-03-14T09:21:00Z"


def test_timestamp_without_timezone_is_rejected_with_a_clear_message():
    with pytest.raises(ValidationError, match="must include a timezone"):
        _incident(created_at="2026-03-14T09:21:00")


def test_enum_and_service_case_is_normalized():
    rec = _incident(environment="PROD", severity="sev2", service="Payroll-Engine").to_record()
    assert (rec["environment"], rec["severity"], rec["service"]) == ("prod", "SEV2", "payroll-engine")


def test_unknown_fields_are_ignored():
    assert "owner" not in _incident(owner="someone").to_record()


@pytest.mark.parametrize(
    "bad",
    [{"id": "bad id"}, {"severity": "urgent"}, {"environment": "production"}, {"tags": []}, {"title": ""}],
)
def test_invalid_records_are_rejected(bad):
    with pytest.raises(ValidationError):
        _incident(**bad)
