from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_llm
from app.llm.base import LLMClient
from app.observability.correlation import get_correlation_id

router = APIRouter(tags=["health"])


@router.get("/health")
def health(llm: Annotated[LLMClient, Depends(get_llm)]) -> dict:
    return {"status": "ok", "llm": llm.describe(), "correlation_id": get_correlation_id()}
