"""FastAPI dependencies. Tests swap these through app.dependency_overrides."""

from typing import Annotated

from fastapi import Depends, Request

from app.assist.service import AssistService
from app.config import Settings
from app.ingest.service import IngestService
from app.llm.base import LLMClient
from app.observability.correlation import get_correlation_id
from app.observability.trace import Trace
from app.search.repository import IncidentRepository
from app.search.service import SearchService


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_llm(request: Request) -> LLMClient:
    return request.app.state.llm


def get_repo(request: Request) -> IncidentRepository:
    return request.app.state.repo


def get_search_service(request: Request) -> SearchService:
    return request.app.state.search_service


def get_ingest_service(request: Request) -> IngestService:
    return request.app.state.ingest_service


def get_assist_service(request: Request, llm: Annotated[LLMClient, Depends(get_llm)]) -> AssistService:
    # built per request so an overridden get_llm (the fake, in tests) is the one that gets used
    state = request.app.state
    return AssistService(state.search_service, state.repo, llm, state.settings)


def get_trace(request: Request):
    """One trace per request, saved to the store whether the endpoint succeeds or fails."""
    trace = Trace(correlation_id=get_correlation_id(), method=request.method, path=request.url.path)
    try:
        yield trace
    except Exception:
        trace.finish("error")
        raise
    else:
        trace.finish("ok")
    finally:
        request.app.state.trace_store.save(trace)
