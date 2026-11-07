"""App factory. The only place concrete adapters get created and wired together."""

import logging

from fastapi import FastAPI

from app.api import routes_health
from app.api.errors import register_exception_handlers
from app.api.limits import BodySizeLimitMiddleware
from app.config import Settings, get_settings
from app.observability.correlation import CorrelationIdMiddleware
from app.observability.logging import setup_logging

log = logging.getLogger("app")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level, settings.log_format)

    app = FastAPI(title="incident-triage", version="0.1.0")
    app.state.settings = settings
    register_exception_handlers(app)

    # add_middleware puts the last one added outermost: the correlation id wraps everything
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes)
    app.add_middleware(CorrelationIdMiddleware)

    app.include_router(routes_health.router)

    if missing := settings.llm_missing_vars():
        log.warning(
            "LLM not configured (missing %s). /search works; /assist returns 503 until it is.",
            ", ".join(missing),
            extra={"event": "llm.not_configured", "missing": missing},
        )
    return app
