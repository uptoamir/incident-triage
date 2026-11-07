.PHONY: setup run data test test-live check

setup:
	uv sync

run:
	uv run python -m app

data:
	uv run python scripts/generate_incidents.py --seed 42 --count 300

test:
	uv run pytest -q

test-live:
	uv run pytest -q -m live

check:
	uv run ruff check . && uv run pytest -q
