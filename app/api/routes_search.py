from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_search_service, get_settings_dep, get_trace
from app.api.schemas import SearchParams
from app.config import Settings
from app.domain.errors import InvalidRequest
from app.observability.correlation import get_correlation_id
from app.observability.trace import Trace
from app.search.service import SearchRequest, SearchService

router = APIRouter(tags=["search"])


@router.get("/search")
def search(
    params: Annotated[SearchParams, Query()],
    service: Annotated[SearchService, Depends(get_search_service)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    trace: Annotated[Trace, Depends(get_trace)],
) -> dict:
    if params.limit > settings.search_max_limit:
        raise InvalidRequest(
            f"limit must be between 1 and {settings.search_max_limit}.",
            how_to_fix=[f"use limit<={settings.search_max_limit}, or raise SEARCH_MAX_LIMIT"],
        )
    if len(params.q) > settings.search_max_query_chars:
        raise InvalidRequest(f"q is longer than {settings.search_max_query_chars} characters.")

    filters = params.to_filters()
    with trace.step(
        "tool:search", {"filters": filters.summary(), "match": params.match, "limit": params.limit}
    ) as s:
        result = service.search(
            SearchRequest(
                q=params.q, filters=filters, match=params.match, limit=params.limit, offset=params.offset
            )
        )
        s.input["terms"] = result.terms
        s.output = {
            "total_hits": result.total,
            "match_mode": result.match_mode,
            "top": [h["id"] for h in result.hits],
        }
    return {
        "query": params.q,
        "terms": result.terms,
        "match_mode": result.match_mode,
        "filters": filters.summary(),
        "total": result.total,
        "limit": params.limit,
        "offset": params.offset,
        "notes": result.notes,
        "results": result.hits,
        "correlation_id": get_correlation_id(),
    }
