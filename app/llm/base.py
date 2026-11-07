"""What the rest of the app knows about LLMs: one JSON call, a typed result, typed errors."""

from dataclasses import dataclass, field
from typing import Protocol

from app.domain.errors import AppError


@dataclass
class LLMResult:
    data: dict
    model: str
    latency_ms: float
    finish_reason: str | None
    usage: dict = field(default_factory=dict)  # {"input": n, "output": n}


class LLMClient(Protocol):
    provider: str
    model: str | None

    def complete_json(
        self,
        system: str,
        user: str,
        schema: dict,
        *,
        schema_name: str,
        timeout_s: float | None = None,
        max_retries: int | None = None,
    ) -> LLMResult: ...

    def describe(self) -> dict: ...


class LLMError(AppError):
    http_status = 502
    code = "llm_error"


class LLMNotConfigured(LLMError):
    http_status = 503
    code = "llm_not_configured"


class LLMAuthError(LLMError):
    code = "llm_auth_failed"


class LLMModelNotFound(LLMError):
    code = "llm_model_not_found"


class LLMBadRequest(LLMError):
    code = "llm_bad_request"


class LLMTimeout(LLMError):
    http_status = 504
    code = "llm_timeout"


class LLMRateLimited(LLMError):
    http_status = 503
    code = "llm_rate_limited"


class LLMUnavailable(LLMError):
    code = "llm_unavailable"


class LLMInvalidOutput(LLMError):
    """details["reason"] is "not_json", "not_object", "schema" or "truncated"."""

    code = "llm_invalid_output"


class LLMRefused(LLMError):
    code = "llm_refused"
