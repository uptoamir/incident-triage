from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_assist_service, get_settings_dep, get_trace
from app.api.schemas import AssistRequest
from app.assist.service import AssistService
from app.config import Settings
from app.domain.errors import InvalidRequest
from app.observability.correlation import get_correlation_id
from app.observability.trace import Trace

router = APIRouter(tags=["assist"])


@router.post("/assist")
def assist(
    body: AssistRequest,
    service: Annotated[AssistService, Depends(get_assist_service)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    trace: Annotated[Trace, Depends(get_trace)],
) -> dict:
    if len(body.question) > settings.assist_max_question_chars:
        raise InvalidRequest(f"question is longer than {settings.assist_max_question_chars} characters.")
    result = service.assist(body.question, body.filters.to_filters(), trace)
    return {**result, "correlation_id": get_correlation_id()}
