"""One real LLM call with the same strict-schema request /assist uses. `make smoke` (reads .env)."""

import sys

from pydantic import ValidationError

from app.config import Settings, format_settings_error
from app.llm.base import LLMError
from app.llm.factory import build_llm_client
from app.observability.logging import setup_logging

SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}, "reply": {"type": "string"}},
    "required": ["ok", "reply"],
    "additionalProperties": False,
}


def main() -> int:
    try:
        settings = Settings()
    except ValidationError as exc:
        print(format_settings_error(exc), file=sys.stderr)
        return 2
    setup_logging(settings.log_level, "text")
    client = build_llm_client(settings)
    try:
        result = client.complete_json(
            "You answer in JSON only.",
            "Set ok to true and reply with three words.",
            SCHEMA,
            schema_name="smoke",
        )
    except LLMError as exc:
        print(f"FAILED {exc.code}: {exc.message}")
        for hint in exc.how_to_fix:
            print(f"  - {hint}")
        if exc.details:
            print(f"  details: {exc.details}")
        return 1
    print(
        f"OK provider={client.provider} model={result.model} latency_ms={result.latency_ms:.0f} "
        f"tokens={result.usage} data={result.data}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
