from fastapi import APIRouter, Request

from app.observability.correlation import get_correlation_id

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request) -> dict:
    settings = request.app.state.settings
    missing = settings.llm_missing_vars()
    return {
        "status": "ok",
        "llm": {
            "provider": settings.llm_provider,
            "model": settings.llm_model,
            "configured": not missing,
            "missing": missing,
        },
        "correlation_id": get_correlation_id(),
    }
