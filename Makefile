.PHONY: setup run data smoke test test-live check ui test-ui

setup:
	uv sync

run:
	uv run python -m app

data:
	uv run python -m scripts.generate_incidents --seed 42 --count 300

smoke:
	uv run python -m scripts.llm_smoke

test:
	uv run pytest -q

test-live:
	uv run pytest -q -m live

check:
	uv run ruff check . && uv run pytest -q

ui:
	uv run --group ui streamlit run ui/app.py

test-ui:
	uv run --group ui pytest -q -m ui
