"""Idempotent ingest: validate each record, normalize, hash, then add / update / skip (PLAN §6.2)."""

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from app.config import Settings
from app.domain.errors import DataSourceError, InvalidRequest
from app.domain.models import Incident
from app.search.repository import IncidentRepository

MAX_REPORTED_ERRORS = 20


def content_hash(record: dict) -> str:
    """sha256 of the canonical record. Normalizing first means tag order or +00:00 vs Z is never a change."""
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_file(path: str) -> list:
    p = Path(path)
    if not p.is_file():
        raise DataSourceError(
            f"Data file not found: {path}",
            how_to_fix=["generate it: make data", "or point DATA_PATH at a file"],
        )
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DataSourceError(f"Can't read {path}: {exc}", how_to_fix=["regenerate it: make data"]) from exc
    if not isinstance(data, list):
        raise DataSourceError(
            f"{path} must contain a JSON array of incidents", how_to_fix=["regenerate it: make data"]
        )
    return data


class IngestService:
    def __init__(self, repo: IncidentRepository, settings: Settings):
        self.repo = repo
        self.settings = settings

    def ingest(self, records: list | None) -> dict:
        started = time.perf_counter()
        if records is None:
            source, raw = f"file:{self.settings.data_path}", load_file(self.settings.data_path)
        else:
            source, raw = "request", records
        if len(raw) > self.settings.ingest_max_records:
            raise InvalidRequest(
                f"{len(raw)} records is over the limit of {self.settings.ingest_max_records}.",
                code="too_many_records",
                how_to_fix=["send fewer records per request, or raise INGEST_MAX_RECORDS"],
            )

        valid, errors, seen = [], [], set()
        for index, item in enumerate(raw):
            item_id = item.get("id") if isinstance(item, dict) else None
            if not isinstance(item, dict):
                errors.append({"index": index, "id": None, "reason": "not a JSON object"})
                continue
            try:
                incident = Incident.model_validate(item)
            except ValidationError as exc:
                first = exc.errors()[0]
                field = ".".join(str(p) for p in first["loc"]) or "record"
                errors.append({"index": index, "id": item_id, "reason": f"{field}: {first['msg']}"})
                continue
            if incident.id in seen:
                errors.append(
                    {"index": index, "id": incident.id, "reason": "duplicate id in payload; first one wins"}
                )
                continue
            seen.add(incident.id)
            record = incident.to_record()
            record["content_hash"] = content_hash(record)
            valid.append(record)

        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        counts = self.repo.upsert_many(valid, now)
        result = {
            "source": source,
            "received": len(raw),
            **counts,
            "invalid": len(errors),
            "errors": errors[:MAX_REPORTED_ERRORS],
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        }
        return result
