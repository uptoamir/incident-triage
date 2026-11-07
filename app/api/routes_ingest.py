from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_ingest_service
from app.api.schemas import IngestBody
from app.ingest.service import IngestService
from app.observability.correlation import get_correlation_id

router = APIRouter(tags=["ingest"])


@router.post("/ingest")
def ingest(
    service: Annotated[IngestService, Depends(get_ingest_service)], body: IngestBody | None = None
) -> dict:
    """No body (or no "incidents" key): load DATA_PATH. A client can never pass a file path."""
    result = service.ingest(body.incidents if body else None)
    return {**result, "correlation_id": get_correlation_id()}
