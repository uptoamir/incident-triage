"""`python -m app`: check config, set up logging, then start uvicorn with our logging, not its own."""

import sys

import uvicorn
from pydantic import ValidationError

from app.config import Settings, format_settings_error
from app.observability.logging import setup_logging


def main() -> None:
    try:
        settings = Settings()
    except ValidationError as exc:
        print(format_settings_error(exc), file=sys.stderr)
        sys.exit(2)
    setup_logging(settings.log_level, settings.log_format)
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    main()
