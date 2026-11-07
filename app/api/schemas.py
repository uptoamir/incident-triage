"""HTTP request models. Character limits live here, not in the services (PLAN §7.1)."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.models import SERVICE_PATTERN, Environment, Severity
from app.search.query_builder import SearchFilters


class FilterFields(BaseModel):
    """Shared by /search (as query params) and /assist (as the "filters" object)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    environment: Environment | None = None
    service: str | None = Field(default=None, pattern=SERVICE_PATTERN)
    severity: Severity | None = None
    tags: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("environment", "service", mode="before")
    @classmethod
    def _lower(cls, v):
        return v.strip().lower() if isinstance(v, str) else v

    @field_validator("severity", mode="before")
    @classmethod
    def _upper(cls, v):
        return v.strip().upper() if isinstance(v, str) else v

    @field_validator("tags", mode="before")
    @classmethod
    def _split_tags(cls, v):
        # accept tags=a&tags=b and tags=a,b
        if isinstance(v, str):
            v = [v]
        if isinstance(v, list):
            return [
                t.strip().lower() for item in v if isinstance(item, str) for t in item.split(",") if t.strip()
            ]
        return v

    def to_filters(self) -> SearchFilters:
        return SearchFilters(
            environment=self.environment.value if self.environment else None,
            service=self.service,
            severity=self.severity.value if self.severity else None,
            tags=tuple(self.tags),
        )


class SearchParams(FilterFields):
    # extra="forbid" (inherited): a typo like env=prod is a 422, not a silently ignored filter
    q: str = Field(min_length=1, max_length=2000)
    match: Literal["auto", "all", "any"] = "auto"
    limit: int = Field(10, ge=1, le=200)  # tightened at runtime to SEARCH_MAX_LIMIT
    offset: int = Field(0, ge=0, le=1000)


class AssistRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=3, max_length=2000)  # tightened at runtime to ASSIST_MAX_QUESTION_CHARS
    filters: FilterFields = Field(default_factory=FilterFields)  # the same filter model /search uses


class IngestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # list[Any], not list[Incident]: one bad record is reported, it doesn't 422 the whole batch
    incidents: list[Any] | None = None
