"""The incident record and its normalization rules (PLAN §5.3)."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
SERVICE_PATTERN = r"^[a-z0-9][a-z0-9-]{1,63}$"
TAG_PATTERN = r"^[a-z0-9-]{1,32}$"


class Environment(StrEnum):
    dev = "dev"
    qa = "qa"
    stage = "stage"
    prod = "prod"


class Severity(StrEnum):
    SEV1 = "SEV1"
    SEV2 = "SEV2"
    SEV3 = "SEV3"
    SEV4 = "SEV4"


Tag = Annotated[str, Field(pattern=TAG_PATTERN)]


class Incident(BaseModel):
    # unknown fields in source records are ignored, not rejected, so the format can grow
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    id: str = Field(pattern=ID_PATTERN)
    created_at: datetime
    environment: Environment
    service: str = Field(pattern=SERVICE_PATTERN)
    severity: Severity
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=10_000)
    resolution_summary: str = Field(min_length=1, max_length=5_000)
    tags: list[Tag] = Field(min_length=1, max_length=10)

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
    def _normalize_tags(cls, v):
        # lowercase, trim, dedupe, sort: tag order or case never counts as a change
        if isinstance(v, list):
            return sorted({t.strip().lower() for t in v if isinstance(t, str) and t.strip()})
        return v

    @field_validator("created_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("created_at must include a timezone, e.g. 2026-03-14T09:21:00Z")
        return v.astimezone(UTC).replace(microsecond=0)

    def to_record(self) -> dict:
        """Canonical form: what gets stored, hashed and returned."""
        return {
            "id": self.id,
            "created_at": self.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "environment": self.environment.value,
            "service": self.service,
            "severity": self.severity.value,
            "title": self.title,
            "description": self.description,
            "resolution_summary": self.resolution_summary,
            "tags": list(self.tags),
        }
