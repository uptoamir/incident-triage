"""FastAPI dependencies. Tests swap these through app.dependency_overrides."""

from fastapi import Request

from app.config import Settings
from app.ingest.service import IngestService
from app.llm.base import LLMClient
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
