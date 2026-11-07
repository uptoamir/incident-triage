import pytest
from pydantic import ValidationError

from app.config import Settings, format_settings_error


def test_cf1_temperature_none_means_dont_send_it(monkeypatch):
    monkeypatch.setenv("LLM_TEMPERATURE", "none")
    assert Settings(_env_file=None).llm_temperature is None


def test_cf1_bad_number_gives_a_readable_error(monkeypatch):
    monkeypatch.setenv("LLM_TEMPERATURE", "abc")
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None)
    text = format_settings_error(exc.value)
    assert "LLM_TEMPERATURE" in text
    assert ".env.example" in text


def test_default_limit_cannot_exceed_max():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, search_default_limit=60, search_max_limit=50)


def test_unknown_provider_fails_at_startup(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "foo")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_missing_llm_vars_are_named():
    s = Settings(_env_file=None, llm_api_key=None, llm_provider="azure-openai")
    assert s.llm_missing_vars() == ["LLM_API_KEY", "AZURE_OPENAI_ENDPOINT"]


def test_incident_id_pattern_is_checked_at_startup():
    with pytest.raises(ValidationError, match="capturing groups"):
        Settings(_env_file=None, incident_id_pattern=r"(?i)\b(INC|TKT)-\d+\b")
    with pytest.raises(ValidationError, match="regular expression"):
        Settings(_env_file=None, incident_id_pattern="[")
    assert Settings(_env_file=None, incident_id_pattern=r"(?i)\b(?:INC|TKT)-\d+\b")
