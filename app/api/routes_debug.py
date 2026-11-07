"""Only registered when DEBUG_ENDPOINTS_ENABLED=true. Traces contain incident data."""

from typing import Annotated

from fastapi import APIRouter, Path, Request

from app.domain.errors import NotFound

router = APIRouter(tags=["debug"])


@router.get("/debug/trace/{correlation_id}")
def get_trace(
    correlation_id: Annotated[str, Path(pattern=r"^[A-Za-z0-9._:-]{1,128}$")], request: Request
) -> dict:
    # no trace dependency here on purpose: fetching a trace must not overwrite it
    trace = request.app.state.trace_store.get(correlation_id)
    if trace is None:
        raise NotFound(
            f"No trace for correlation id {correlation_id}.",
            code="trace_not_found",
            how_to_fix=[
                "only the last TRACE_STORE_MAX requests are kept, in memory",
                "send the request again with an X-Correlation-ID header, then fetch it",
            ],
        )
    return trace
