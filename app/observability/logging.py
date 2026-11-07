"""Logging setup: one handler on the root logger, and every line carries correlation_id."""

import json
import logging
import sys
from datetime import UTC, datetime

from app.observability.correlation import get_correlation_id

_MARK = "_incident_triage_handler"
# attributes every LogRecord has; anything else came in through `extra=`
_RESERVED = set(vars(logging.LogRecord("x", 0, "x", 0, "x", None, None))) | {
    "message",
    "asctime",
    "correlation_id",
    "color_message",  # uvicorn sends a copy of msg full of ANSI color codes; noise in JSON
}


class CorrelationIdFilter(logging.Filter):
    """Goes on the handler, not a logger.

    A logger-level filter never sees records that propagate up from child loggers
    (uvicorn, httpx, openai), so those lines would lose the ID.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds").replace(
                "+00:00", "Z"
            ),
            "level": record.levelname,
            "logger": record.name,
            "correlation_id": getattr(record, "correlation_id", "-"),
            "event": getattr(record, "event", "log"),
            "msg": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key not in _RESERVED and key not in out:
                out[key] = value
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    def __init__(self):
        super().__init__("%(asctime)s %(levelname)-7s %(name)s [cid=%(correlation_id)s] %(message)s")


def setup_logging(level: str = "INFO", fmt: str = "json") -> None:
    """Idempotent: safe to call from both `python -m app` and create_app()."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _MARK, False):
            root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    setattr(handler, _MARK, True)
    handler.addFilter(CorrelationIdFilter())
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    root.addHandler(handler)
    root.setLevel(level)

    # The plain `uvicorn` CLI installs its own handlers before our app exists. Drop them,
    # otherwise every uvicorn line prints twice and one copy has no ID.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
    logging.getLogger("uvicorn.access").disabled = True  # our middleware writes the access line
