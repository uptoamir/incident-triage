from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_llm
from app.llm.base import LLMClient
from app.observability.correlation import get_correlation_id

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request, llm: Annotated[LLMClient, Depends(get_llm)]) -> dict:
    """Never returns secrets and never calls the LLM."""
    try:
        count, db = request.app.state.repo.count_all(), "ok"
    except Exception:  # health must answer even when the DB doesn't
        count, db = None, "error"
    return {
        "status": "ok" if db == "ok" else "degraded",
        "db": db,
        "incident_count": count,
        "fts5": request.app.state.db.fts5_available(),
        "llm": llm.describe(),
        "correlation_id": get_correlation_id(),
    }
