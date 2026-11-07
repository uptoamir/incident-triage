import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.deps import get_llm
from app.llm.base import LLMClient
from app.observability.correlation import get_correlation_id

router = APIRouter(tags=["health"])
log = logging.getLogger("app.health")


@router.get("/health")
def health(request: Request, llm: Annotated[LLMClient, Depends(get_llm)]) -> JSONResponse:
    """Never returns secrets and never calls the LLM. 503 when the database isn't usable, so probes notice."""
    try:
        count, db = request.app.state.repo.count_all(), "ok"
    except Exception:  # health must still answer; the cause goes to the log, not the response
        log.exception("health check: database not usable", extra={"event": "health.db_error"})
        count, db = None, "error"
    body = {
        "status": "ok" if db == "ok" else "degraded",
        "db": db,
        "incident_count": count,
        "fts5": request.app.state.db.fts5_available(),
        "llm": llm.describe(),
        "correlation_id": get_correlation_id(),
    }
    return JSONResponse(body, status_code=200 if db == "ok" else 503)
