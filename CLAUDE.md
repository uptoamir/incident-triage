# House rules for AI assistants in this repo

Read `docs/PLAN.md` first. It's the spec. Cite sections (`PLAN.md §7.2`) instead of re-describing things.

## Stack
- Python 3.12 via uv (`uv sync`, `uv run`). FastAPI >= 0.115, Pydantic v2 only, stdlib `sqlite3`, `openai` SDK.
- Sync handlers and the sync OpenAI client. No async.
- No new dependencies without asking.

## Code
- Routers stay thin: validate, call a service, map errors. Services don't import FastAPI.
- Only `create_app()` wires concrete adapters. No fakes under `app/`; they live in `tests/`.
- SQL uses placeholders only. Never build SQL or FTS strings from user input with f-strings.
- Never `INSERT OR REPLACE`. Writes use `BEGIN IMMEDIATE`.
- Tests use a temp-file DB, never `:memory:`.
- Request context lives in `contextvars`. No other module-level mutable state.
- Every external call has an explicit timeout. Every error maps to the error envelope with `how_to_fix`.

## Workflow
- One module per change, with its tests. Pure functions get their tests first.
- Before coding, list assumptions. After, list what you didn't do.
- Don't touch files outside the module you're working on.
- `make check` has to pass before anything counts as done.
