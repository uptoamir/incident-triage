from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_ingest_service, get_trace
from app.api.schemas import IngestBody
from app.ingest.service import IngestService
from app.observability.correlation import get_correlation_id
from app.observability.trace import Trace

router = APIRouter(tags=["ingest"])


@router.post("/ingest")
def ingest(
    service: Annotated[IngestService, Depends(get_ingest_service)],
    trace: Annotated[Trace, Depends(get_trace)],
    body: IngestBody | None = None,
) -> dict:
    """No body (or no "incidents" key): load DATA_PATH. A client can never pass a file path."""
    records = body.incidents if body else None
    with trace.step("ingest.upsert", {"source": "request" if records is not None else "file"}) as s:
        result = service.ingest(records)
        s.output = {k: result[k] for k in ("received", "ingested", "updated", "skipped", "invalid")}
    return {**result, "correlation_id": get_correlation_id()}
