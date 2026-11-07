from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.api.deps import get_repo
from app.domain.errors import NotFound
from app.domain.models import ID_PATTERN
from app.observability.correlation import get_correlation_id
from app.search.repository import IncidentRepository

router = APIRouter(tags=["incidents"])


@router.get("/incidents/{incident_id}")
def get_incident(
    incident_id: Annotated[str, Path(pattern=ID_PATTERN)],
    repo: Annotated[IncidentRepository, Depends(get_repo)],
) -> dict:
    record = repo.get(incident_id)
    if record is None:
        raise NotFound(
            f"Incident {incident_id} not found.",
            code="incident_not_found",
            how_to_fix=["check the id", "did you run POST /ingest?"],
        )
    return {**record, "correlation_id": get_correlation_id()}
