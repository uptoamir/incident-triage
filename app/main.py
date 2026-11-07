"""App factory. The only place concrete adapters get created and wired together."""

import logging

from fastapi import FastAPI

from app.api import routes_health, routes_incidents, routes_ingest, routes_search
from app.api.errors import register_exception_handlers
from app.api.limits import BodySizeLimitMiddleware
from app.config import Settings, get_settings
from app.ingest.service import IngestService
from app.llm.factory import build_llm_client
from app.observability.correlation import CorrelationIdMiddleware
from app.observability.logging import setup_logging
from app.search.db import Database
from app.search.repository import SqliteIncidentRepository
from app.search.service import SearchService

log = logging.getLogger("app")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level, settings.log_format)

    db = Database(settings.db_path)
    db.init_schema()  # fails fast with a clear message if this SQLite has no FTS5
    repo = SqliteIncidentRepository(db)

    app = FastAPI(title="incident-triage", version="0.1.0")
    app.state.settings = settings
    app.state.db = db
    app.state.repo = repo
    app.state.search_service = SearchService(repo, settings)
    app.state.ingest_service = IngestService(repo, settings)
    app.state.llm = build_llm_client(settings)
    register_exception_handlers(app)

    # add_middleware puts the last one added outermost: the correlation id wraps everything
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes)
    app.add_middleware(CorrelationIdMiddleware)

    for module in (routes_health, routes_ingest, routes_search, routes_incidents):
        app.include_router(module.router)

    if missing := settings.llm_missing_vars():
        log.warning(
            "LLM not configured (missing %s). /search works; /assist returns 503 until it is.",
            ", ".join(missing),
            extra={"event": "llm.not_configured", "missing": missing},
        )
    return app
