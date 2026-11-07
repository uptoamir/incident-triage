import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_search_service, get_settings_dep
from app.api.schemas import SearchParams
from app.config import Settings
from app.domain.errors import InvalidRequest
from app.observability.correlation import get_correlation_id
from app.search.service import SearchRequest, SearchService

router = APIRouter(tags=["search"])
log = logging.getLogger("app.search")


@router.get("/search")
def search(
    params: Annotated[SearchParams, Query()],
    service: Annotated[SearchService, Depends(get_search_service)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> dict:
    if params.limit > settings.search_max_limit:
        raise InvalidRequest(
            f"limit must be between 1 and {settings.search_max_limit}.",
            how_to_fix=[f"use limit<={settings.search_max_limit}, or raise SEARCH_MAX_LIMIT"],
        )
    if len(params.q) > settings.search_max_query_chars:
        raise InvalidRequest(f"q is longer than {settings.search_max_query_chars} characters.")

    result = service.search(
        SearchRequest(
            q=params.q,
            filters=params.to_filters(),
            match=params.match,
            limit=params.limit,
            offset=params.offset,
        )
    )
    log.info(
        "search: %d hits",
        result.total,
        extra={
            "event": "search",
            "input": {"terms": result.terms, "filters": params.summary(), "match": params.match},
            "output": {
                "total": result.total,
                "match_mode": result.match_mode,
                "top_ids": [h["id"] for h in result.hits],
            },
        },
    )
    return {
        "query": params.q,
        "terms": result.terms,
        "match_mode": result.match_mode,
        "filters": params.summary(),
        "total": result.total,
        "limit": params.limit,
        "offset": params.offset,
        "notes": result.notes,
        "results": result.hits,
        "correlation_id": get_correlation_id(),
    }
