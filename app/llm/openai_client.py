"""OpenAI / Azure OpenAI adapter. Every setting is passed explicitly; nothing relies on SDK defaults."""

import json
import logging
import re
import time

import openai

from app.config import Settings
from app.llm.base import (
    LLMAuthError,
    LLMBadRequest,
    LLMInvalidOutput,
    LLMModelNotFound,
    LLMRateLimited,
    LLMRefused,
    LLMResult,
    LLMTimeout,
    LLMUnavailable,
)

log = logging.getLogger("app.llm")
_KEYLIKE = re.compile(r"sk-[A-Za-z0-9_\-*]{6,}")


def _scrub(text: str | None, limit: int = 300) -> str:
    """Provider messages sometimes echo part of the key back. Never pass that through."""
    return _KEYLIKE.sub("sk-***", text or "")[:limit]


def _log_attempt(request) -> None:
    # The SDK logs its retries at DEBUG, so at INFO they'd be invisible. This logs every
    # attempt, timeouts included, and the log filter adds the correlation id.
    attempt = int(request.headers.get("x-stainless-retry-count") or 0) + 1
    log.info(
        "llm http attempt %d",
        attempt,
        extra={"event": "llm.http_attempt", "attempt": attempt, "path": request.url.path},
    )


class OpenAIChatClient:
    def __init__(self, settings: Settings, *, transport=None):
        self.provider = settings.llm_provider
        self.model = settings.llm_model
        self._settings = settings
        # The SDK default is a 10 minute timeout; never rely on it. Use openai.Timeout, not
        # httpx.Timeout: SDK v3 runs on httpx2, and an httpx.Timeout passed in turns into a
        # broken timeout object instead of an error.
        timeout = openai.Timeout(settings.llm_timeout_seconds, connect=5.0)
        http_client = openai.DefaultHttpxClient(
            timeout=timeout, transport=transport, event_hooks={"request": [_log_attempt]}
        )
        common = {
            "api_key": settings.llm_api_key.get_secret_value(),
            "timeout": timeout,
            "max_retries": settings.llm_max_retries,
            "http_client": http_client,
        }
        if settings.llm_provider == "azure-openai":
            self._client = openai.AzureOpenAI(
                azure_endpoint=settings.azure_openai_endpoint,
                api_version=settings.azure_openai_api_version,
                **common,
            )
        else:
            base_url = settings.llm_base_url or "https://api.openai.com/v1"
            self._client = openai.OpenAI(base_url=base_url, **common)

    def describe(self) -> dict:
        return {"provider": self.provider, "model": self.model, "configured": True, "missing": []}

    def complete_json(
        self, system: str, user: str, schema: dict, *, schema_name: str, timeout_s: float | None = None
    ) -> LLMResult:
        s = self._settings
        if s.llm_json_mode == "json_schema":
            response_format = {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            }
        else:
            response_format = {"type": "json_object"}
        kwargs = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": response_format,
            "max_completion_tokens": s.llm_max_output_tokens,
        }
        if s.llm_temperature is not None:  # some newer models reject it; LLM_TEMPERATURE=none skips it
            kwargs["temperature"] = s.llm_temperature
        if timeout_s is not None:
            kwargs["timeout"] = timeout_s

        started = time.perf_counter()
        try:
            resp = self._client.chat.completions.create(**kwargs)
        except openai.APITimeoutError as exc:
            # must come before APIConnectionError: in this SDK a timeout *is* a connection error
            raise LLMTimeout(
                f"No response from the LLM within LLM_TIMEOUT_SECONDS ({s.llm_timeout_seconds:g} s).",
                how_to_fix=["retry", "or raise LLM_TIMEOUT_SECONDS"],
            ) from exc
        except openai.APIConnectionError as exc:
            raise LLMUnavailable(
                "Couldn't reach the LLM endpoint.",
                how_to_fix=["check the network or proxy", "check LLM_BASE_URL or AZURE_OPENAI_ENDPOINT"],
            ) from exc
        except (openai.AuthenticationError, openai.PermissionDeniedError) as exc:
            raise LLMAuthError(
                "The LLM provider rejected the credentials.",
                how_to_fix=["check LLM_API_KEY", "for Azure, also check AZURE_OPENAI_ENDPOINT"],
            ) from exc
        except openai.NotFoundError as exc:
            raise LLMModelNotFound(
                f"Model '{self.model}' was not found.",
                how_to_fix=[
                    "check LLM_MODEL exists and this key can use it",
                    "for Azure, LLM_MODEL must be your deployment name",
                ],
            ) from exc
        except openai.RateLimitError as exc:
            retry_after = exc.response.headers.get("retry-after") if exc.response is not None else None
            raise LLMRateLimited(
                "The LLM provider is rate limiting requests.",
                how_to_fix=[
                    "wait and retry",
                    "if the message says insufficient_quota, the account needs credit",
                ],
                details={"provider_message": _scrub(exc.message)},
                headers={"Retry-After": retry_after} if retry_after else None,
            ) from exc
        except openai.BadRequestError as exc:
            raise LLMBadRequest(
                "The LLM provider rejected the request.",
                how_to_fix=[
                    "if it mentions temperature: set LLM_TEMPERATURE=none",
                    "if it mentions response_format or json_schema: use a model with structured outputs, "
                    "or set LLM_JSON_MODE=json_object",
                ],
                details={"provider_message": _scrub(exc.message)},
            ) from exc
        except openai.APIStatusError as exc:
            raise LLMUnavailable(
                f"The LLM provider returned HTTP {exc.status_code}.",
                how_to_fix=["retry in a bit", "check the provider's status page"],
            ) from exc
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        return _parse(resp, latency_ms)


def _parse(resp, latency_ms: float) -> LLMResult:
    choice = resp.choices[0]
    message = choice.message
    if getattr(message, "refusal", None):
        raise LLMRefused(
            "The model refused to answer.",
            how_to_fix=["rephrase the question"],
            details={"refusal": _scrub(message.refusal)},
        )
    if choice.finish_reason == "length":
        raise LLMInvalidOutput(
            "The model's answer was cut off.",
            how_to_fix=["retry", "or raise LLM_MAX_OUTPUT_TOKENS"],
            details={"reason": "truncated"},
        )
    try:
        data = json.loads(message.content or "")
    except json.JSONDecodeError:
        raise LLMInvalidOutput(
            "The model didn't return valid JSON.", how_to_fix=["retry"], details={"reason": "not_json"}
        ) from None
    if not isinstance(data, dict):
        raise LLMInvalidOutput(
            "The model returned JSON that isn't an object.",
            how_to_fix=["retry"],
            details={"reason": "not_object"},
        )
    usage = {"input": resp.usage.prompt_tokens, "output": resp.usage.completion_tokens} if resp.usage else {}
    return LLMResult(
        data=data, model=resp.model, latency_ms=latency_ms, finish_reason=choice.finish_reason, usage=usage
    )
