"""FastAPI dependencies. Tests swap these through app.dependency_overrides."""

from fastapi import Request

from app.config import Settings
from app.llm.base import LLMClient


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_llm(request: Request) -> LLMClient:
    return request.app.state.llm
