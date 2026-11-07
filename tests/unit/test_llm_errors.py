"""The real SDK against a fake transport: no network, but the SDK's own error and retry paths run.

openai v3 runs on httpx2, not httpx, so the fake transport and exceptions come from httpx2.
"""

import json

import httpx2
import pytest

from app.config import Settings
from app.llm.base import (
    LLMAuthError,
    LLMBadRequest,
    LLMInvalidOutput,
    LLMModelNotFound,
    LLMNotConfigured,
    LLMRateLimited,
    LLMTimeout,
    LLMUnavailable,
)
from app.llm.factory import build_llm_client
from app.llm.openai_client import OpenAIChatClient
from app.observability.correlation import correlation_id_var

CANARY = "sk-canary-0123456789abcdef"
SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}


def _settings(**over) -> Settings:
    values = {"_env_file": None, "llm_api_key": CANARY, "llm_max_retries": 0, "llm_timeout_seconds": 5}
    values.update(over)
    return Settings(**values)


def _completion(content='{"ok": true}', finish_reason="stop") -> dict:
    return {
        "id": "c1",
        "object": "chat.completion",
        "created": 0,
        "model": "gpt-4o-mini",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content, "refusal": None},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
    }


def _client(handler, **over) -> OpenAIChatClient:
    return OpenAIChatClient(_settings(**over), transport=httpx2.MockTransport(handler))


def _call(client):
    return client.complete_json("system", "user", SCHEMA, schema_name="t")


def test_timeout_is_really_applied():
    # regression: an httpx.Timeout handed to the httpx2-based SDK became a broken object, not 20 s
    client = OpenAIChatClient(_settings(llm_timeout_seconds=20))
    timeout = client._client.timeout
    assert (timeout.read, timeout.connect) == (20, 5.0)


def test_success_returns_parsed_json_and_usage():
    result = _call(_client(lambda req: httpx2.Response(200, json=_completion())))
    assert result.data == {"ok": True}
    assert result.usage == {"input": 11, "output": 3}


def test_request_uses_strict_schema_and_sends_temperature():
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return httpx2.Response(200, json=_completion())

    _call(_client(handler))
    assert seen["response_format"]["type"] == "json_schema"
    assert seen["response_format"]["json_schema"]["strict"] is True
    assert seen["temperature"] == 0
    assert seen["max_completion_tokens"] == 1000


def test_temperature_none_is_not_sent_and_json_object_mode_works():
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return httpx2.Response(200, json=_completion())

    _call(_client(handler, llm_temperature=None, llm_json_mode="json_object"))
    assert "temperature" not in seen
    assert seen["response_format"] == {"type": "json_object"}


def test_ll2_timeout_maps_to_timeout_not_unavailable():
    # in this SDK APITimeoutError subclasses APIConnectionError; catch order matters
    def handler(req):
        raise httpx2.ReadTimeout("slow", request=req)

    with pytest.raises(LLMTimeout) as exc:
        _call(_client(handler))
    assert exc.value.http_status == 504
    assert "LLM_TIMEOUT_SECONDS" in exc.value.message


def test_connection_error_maps_to_unavailable():
    def handler(req):
        raise httpx2.ConnectError("dns failed", request=req)

    with pytest.raises(LLMUnavailable):
        _call(_client(handler))


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, LLMAuthError),
        (403, LLMAuthError),
        (404, LLMModelNotFound),
        (400, LLMBadRequest),
        (429, LLMRateLimited),
        (503, LLMUnavailable),
    ],
)
def test_status_codes_map_to_typed_errors(status, error):
    body = {"error": {"message": "nope", "type": "x", "code": None}}
    with pytest.raises(error):
        _call(_client(lambda req: httpx2.Response(status, json=body)))


def test_rate_limit_passes_retry_after_through():
    def handler(req):
        return httpx2.Response(429, json={"error": {"message": "slow down"}}, headers={"retry-after": "7"})

    with pytest.raises(LLMRateLimited) as exc:
        _call(_client(handler))
    assert exc.value.headers == {"Retry-After": "7"}


@pytest.mark.parametrize(
    ("content", "finish", "reason"),
    [
        ("not json", "stop", "not_json"),
        ("[1, 2]", "stop", "not_object"),
        ('{"ok": tr', "length", "truncated"),
    ],
)
def test_bad_output_is_invalid_output_with_a_reason(content, finish, reason):
    with pytest.raises(LLMInvalidOutput) as exc:
        _call(_client(lambda req: httpx2.Response(200, json=_completion(content, finish))))
    assert exc.value.details["reason"] == reason


def test_ll3_key_never_leaks_into_errors_or_logs(log_lines):
    # providers sometimes echo the key back in the error message
    body = {"error": {"message": f"Incorrect API key provided: {CANARY}", "type": "invalid_request_error"}}
    for status in (400, 401):
        with pytest.raises((LLMAuthError, LLMBadRequest)) as exc:
            _call(_client(lambda req, s=status: httpx2.Response(s, json=body)))
        err = exc.value
        assert CANARY not in json.dumps({"m": err.message, "h": err.how_to_fix, "d": err.details})
    assert all(CANARY not in json.dumps(line) for line in log_lines())


def test_every_attempt_is_logged_with_the_correlation_id(log_lines):
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx2.Response(500, json={"error": {"message": "boom"}})
        return httpx2.Response(200, json=_completion())

    token = correlation_id_var.set("cid-llm")
    try:
        _call(_client(handler, llm_max_retries=1))
    finally:
        correlation_id_var.reset(token)
    attempts = [line for line in log_lines() if line["event"] == "llm.http_attempt"]
    assert [a["attempt"] for a in attempts] == [1, 2]
    assert all(a["correlation_id"] == "cid-llm" for a in attempts)


def test_ll1_unconfigured_client_names_the_missing_vars():
    client = build_llm_client(Settings(_env_file=None, llm_api_key=None))
    with pytest.raises(LLMNotConfigured) as exc:
        _call(client)
    assert exc.value.http_status == 503
    assert "LLM_API_KEY" in exc.value.message
    assert any("make run" in hint for hint in exc.value.how_to_fix)


def test_ll1_azure_variant_names_the_endpoint():
    client = build_llm_client(Settings(_env_file=None, llm_api_key="k", llm_provider="azure-openai"))
    with pytest.raises(LLMNotConfigured) as exc:
        _call(client)
    assert exc.value.details["missing"] == ["AZURE_OPENAI_ENDPOINT"]


def test_health_reports_llm_not_configured(client):
    llm = client.get("/health").json()["llm"]
    assert llm["configured"] is False
    assert llm["missing"] == ["LLM_API_KEY"]
