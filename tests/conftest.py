import io
import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.observability.logging import CorrelationIdFilter, JsonFormatter


@pytest.fixture
def settings(tmp_path) -> Settings:
    # _env_file=None: tests never read the developer's .env (or its real key)
    return Settings(_env_file=None, db_path=str(tmp_path / "test.db"), llm_api_key=None, log_format="json")


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def log_lines():
    """Captures records the way production does: filter on the handler, JSON formatter."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(CorrelationIdFilter())
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.addHandler(handler)
    yield lambda: [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]
    root.removeHandler(handler)
