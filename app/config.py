"""All configuration, read from environment variables (and an optional .env)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # lets LLM_TEMPERATURE=none mean "don't send it" instead of failing startup
        env_parse_none_str="none",
    )

    host: str = "127.0.0.1"
    port: int = Field(8000, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "text"] = "json"
    log_llm_payloads: bool = False

    data_path: str = "data/incidents.json"
    db_path: str = "var/incidents.db"

    search_default_limit: int = Field(10, ge=1)
    search_max_limit: int = Field(50, ge=1, le=200)
    search_max_query_chars: int = Field(2000, ge=1)
    search_max_terms: int = Field(16, ge=1, le=64)

    assist_candidates: int = Field(12, ge=1, le=20)  # 8 gave recall 15/20 on golden.json, 12 gives 18/20
    assist_max_question_chars: int = Field(2000, ge=3)
    assist_max_context_chars: int = Field(12000, ge=1000)
    assist_deadline_seconds: float = Field(45, gt=0)
    guardrail_mode: Literal["strict", "lenient"] = "strict"
    incident_id_pattern: str = r"(?i)\bINC-\d+\b"

    llm_provider: Literal["openai", "azure-openai"] = "openai"
    llm_api_key: SecretStr | None = None
    llm_model: str | None = "gpt-4o-mini"
    llm_base_url: str | None = None
    azure_openai_endpoint: str | None = None
    azure_openai_api_version: str = "2024-10-21"
    llm_json_mode: Literal["json_schema", "json_object"] = "json_schema"
    llm_timeout_seconds: float = Field(20, gt=0, le=120)
    llm_max_retries: int = Field(1, ge=0, le=5)
    llm_temperature: float | None = Field(0.0, ge=0, le=2)
    llm_max_output_tokens: int = Field(1000, ge=100, le=8000)

    ingest_max_records: int = Field(1000, ge=1)
    max_request_bytes: int = Field(5_242_880, ge=1024)
    debug_endpoints_enabled: bool = True
    trace_store_max: int = Field(500, ge=10)

    @model_validator(mode="after")
    def _check_consistency(self) -> "Settings":
        if self.search_default_limit > self.search_max_limit:
            raise ValueError("SEARCH_DEFAULT_LIMIT must not be greater than SEARCH_MAX_LIMIT")
        return self

    def llm_missing_vars(self) -> list[str]:
        """Env vars /assist still needs. Empty list means the LLM is configured."""
        missing = []
        key = self.llm_api_key.get_secret_value().strip() if self.llm_api_key else ""
        if not key:
            missing.append("LLM_API_KEY")
        if not (self.llm_model or "").strip():
            missing.append("LLM_MODEL")
        if self.llm_provider == "azure-openai" and not (self.azure_openai_endpoint or "").strip():
            missing.append("AZURE_OPENAI_ENDPOINT")
        return missing


def format_settings_error(exc: ValidationError) -> str:
    """Turn a pydantic error into something a person can act on."""
    lines = ["Invalid configuration:"]
    for err in exc.errors():
        name = str(err["loc"][0]).upper() if err["loc"] else "(settings)"
        lines.append(f"  {name}: {err['msg']}")
    lines.append("Fix these in your environment or .env (see .env.example), then run `make run` again.")
    return "\n".join(lines)


@lru_cache
def get_settings() -> Settings:
    return Settings()
