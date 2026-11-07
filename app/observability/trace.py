"""Per-request step traces. Each step writes one log line and one trace entry, so they can't drift apart."""

import logging
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

log = logging.getLogger("app.trace")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass
class Step:
    seq: int
    name: str
    input: dict
    output: dict = field(default_factory=dict)
    status: str = "ok"
    started_at: str = field(default_factory=_now)
    duration_ms: float = 0.0
    level: int = logging.INFO  # a step can raise this, e.g. when guardrails dropped something


@dataclass
class Trace:
    correlation_id: str
    method: str
    path: str
    started_at: str = field(default_factory=_now)
    status: str = "ok"
    duration_ms: float | None = None
    steps: list[Step] = field(default_factory=list)
    _t0: float = field(default_factory=time.perf_counter, repr=False)

    @contextmanager
    def step(self, name: str, input: dict | None = None):
        step = Step(seq=len(self.steps) + 1, name=name, input=input or {})
        t0 = time.perf_counter()
        try:
            yield step
        except Exception as exc:
            step.status = "error"
            step.output = {**step.output, "error": getattr(exc, "code", type(exc).__name__)}
            raise
        finally:
            step.duration_ms = round((time.perf_counter() - t0) * 1000, 1)
            self.steps.append(step)
            log.log(
                step.level if step.status == "ok" else logging.WARNING,
                "step %s %s",
                name,
                step.status,
                extra={
                    "event": "step",
                    "step": name,
                    "status": step.status,
                    "input": step.input,
                    "output": step.output,
                    "duration_ms": step.duration_ms,
                },
            )

    def finish(self, status: str) -> None:
        self.status = status
        self.duration_ms = round((time.perf_counter() - self._t0) * 1000, 1)

    def to_dict(self) -> dict:
        return {
            "correlation_id": self.correlation_id,
            "method": self.method,
            "path": self.path,
            "started_at": self.started_at,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "steps": [
                {
                    "seq": s.seq,
                    "name": s.name,
                    "status": s.status,
                    "started_at": s.started_at,
                    "duration_ms": s.duration_ms,
                    "input": s.input,
                    "output": s.output,
                }
                for s in self.steps
            ],
        }


class TraceStore:
    """In memory, bounded (LRU), thread-safe. Lost on restart and per-process: debugging only."""

    def __init__(self, max_entries: int):
        self._max = max_entries
        self._data: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.Lock()

    def save(self, trace: Trace) -> None:
        with self._lock:
            self._data[trace.correlation_id] = trace.to_dict()  # a reused id: latest trace wins
            self._data.move_to_end(trace.correlation_id)
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    def get(self, correlation_id: str) -> dict | None:
        with self._lock:
            return self._data.get(correlation_id)
