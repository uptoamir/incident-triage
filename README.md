# incident-triage

Search over past incidents, plus an assistant that suggests similar incidents, next steps and a customer reply, using only what search actually found.

FastAPI · SQLite FTS5 · OpenAI or Azure OpenAI · Python 3.12

## Run it

You need [uv](https://docs.astral.sh/uv/) and an OpenAI key. Don't use the macOS system `python3`: it's 3.9.

```bash
make setup             # uv sync: Python 3.12 + locked deps
cp .env.example .env   # then set LLM_API_KEY (LLM_MODEL defaults to gpt-4o-mini)
make smoke             # optional: one real LLM call, to check the key
make run               # http://127.0.0.1:8000, API docs at /docs
```

## Try it

In a second terminal:

```bash
# load the 300 generated incidents (run it twice: the second run skips all 300)
curl -s -X POST http://127.0.0.1:8000/ingest | python3 -m json.tool

# search: text plus filters
curl -s "http://127.0.0.1:8000/search?q=payroll%20timeout&environment=prod&tags=database&limit=5" | python3 -m json.tool

# one incident
curl -s http://127.0.0.1:8000/incidents/INC-00004 | python3 -m json.tool

# ask the assistant
curl -s -X POST http://127.0.0.1:8000/assist \
  -H 'Content-Type: application/json' -H 'X-Correlation-ID: demo-1' \
  -d '{"question":"Payroll run is timing out in prod and logs show connection pool exhausted errors. What should we check?"}' \
  | python3 -m json.tool

# what /assist did, step by step
curl -s http://127.0.0.1:8000/debug/trace/demo-1 | python3 -m json.tool
```

Worth trying:
- `{"question":"What's a good recipe for sourdough bread?"}` gives `insufficient_context`, and the LLM is never called.
- `/assist` with no `LLM_API_KEY` gives a 503 `llm_not_configured` that says what to set. `/search` keeps working.
- `/search?q=timeout&env=prod` gives a 422 `unknown_query_parameter`, because a typo shouldn't be silently ignored.
- To replay what `/assist` searched: `/search?q=<the question>&match=any&limit=12`.

## Visual tour (ui-demo branch only)

A small Streamlit app that drives every endpoint through the real API. It's for walking through the project. `main` is the submission.

```bash
make run   # the API, in one terminal
make ui    # the UI, in another: http://localhost:8501
```

Every request panel shows the exact curl command, its correlation ID and the raw JSON.

| Tab | What it shows |
|---|---|
| Overview | Each part of the brief, and which tab shows it |
| Ingest | Run it twice (the second run skips all 300), or send a batch with bad records and an unknown field |
| Search | Presets for all-words matching, the any-word fallback, filters, hostile input and filler-only queries. "Full record" on any hit |
| Incident | One record, plus the 404 and 422 cases |
| Assist | The golden questions as presets. Shows verified quotes, next steps with their sources, the customer draft, what the guardrails removed, what search found, and LLM timing and tokens. "Replay the search" checks that `/search` returns the same candidates. "Show the trace" opens the request's steps |
| Trace | The step log for any correlation ID |
| Errors & limits | 13 bad requests, one button each, all returning the error envelope |

The sidebar shows API health (DB, FTS5, incident count, whether the LLM is set up) and the last 12 requests. Streamlit sits in an optional `ui` dependency group, so `make setup` and `make test` don't need it.

## Tests

```bash
make test        # 131 tests, offline, no key needed (fake LLM, temp SQLite)
make test-live   # the 7 golden questions against the real LLM; checks invariants, not wording
make test-ui     # 6 tests that click through the UI against the running API (ui-demo branch)
make check       # ruff + tests
```

## How it works

- **Ingest:** validates each record and normalizes it (UTC times, tag order and case), then hashes it. New, changed and unchanged records come back as ingested, updated and skipped. It all runs in one `BEGIN IMMEDIATE` transaction, so running it twice changes nothing.
- **Search:** words become quoted FTS5 terms, so user text can't inject FTS syntax. Filters are bound parameters, and results are ranked by BM25. The default `match=auto` tries all words first, then any word.
- **Assist:**
  - It calls the same `SearchService` as `/search`, logged as `tool:search`, and skips the LLM when nothing matches.
  - It sends the top 12 results with a strict JSON schema, then checks the reply in code:
    - It can only cite incidents it was shown, and each one needs a word-for-word quote of 3+ words from its own record.
    - Anything the model writes may only mention cited incidents. Lookalike dashes are folded first.
    - The server decides `ok`, `partial` or `insufficient_context`.
    - Titles, services and dates come from the database, not the model.
    - The customer draft never contains incident IDs and is marked for human review.
- **Logs:** every log line is JSON with a `correlation_id`. Send `X-Correlation-ID` or get one generated. `/debug/trace/{id}` shows each step.

`TRADEOFFS.md` lists what's guaranteed and what's best effort.

## Config

Everything is in `.env.example`, with defaults. The settings you're most likely to change:

| Variable | What it does |
|---|---|
| `LLM_PROVIDER` | `openai` or `azure-openai` |
| `LLM_API_KEY` | Your API key |
| `LLM_MODEL` | The model to use. For Azure, this is your deployment name. |
| `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_VERSION` | Needed for Azure only |
| `LLM_TEMPERATURE` | Set to `none` for models that reject a temperature value |
| `GUARDRAIL_MODE` | `strict` (default) or `lenient` |
| `DEBUG_ENDPOINTS_ENABLED` | Turns `/debug/trace` on or off. Turn it off anywhere shared. |

## Errors

Every error has the same shape: `{"error": {"code", "message", "how_to_fix", "details", "correlation_id"}}`.

LLM failures:

| Code | HTTP status |
|---|---|
| `llm_not_configured` | 503 |
| `llm_auth_failed` | 502 |
| `llm_model_not_found` | 502 |
| `llm_bad_request` | 502 |
| `llm_timeout` | 504 |
| `llm_rate_limited` | 503 |
| `llm_unavailable` | 502 |
| `llm_invalid_output` | 502 |
| `llm_refused` | 502 |

When search already ran, these errors also list what it found in `details.retrieved`.

## Data

- `data/incidents.json`: 300 generated incidents (seed 42), committed. `make data` regenerates it byte for byte.
- `data/golden.json`: the 7 test questions and their expected incident IDs.

## Layout

```
app/api            routes, request models, error envelope
app/search         FTS5 store, query builder, search service
app/ingest         idempotent ingest
app/assist         prompt, context, guardrails, the /assist pipeline
app/llm            OpenAI / Azure adapter
app/observability  correlation id, JSON logs, traces
scripts/           data generator, LLM smoke test
ui/                Streamlit visual tour (ui-demo branch only)
tests/             unit, integration, live, ui
docs/PLAN.md       the spec, plus a "changes during the build" table
docs/planning/     how the plan was made (4 plans, 2 review rounds)
docs/diagrams/     how-it-grew.drawio (open in app.diagrams.net)
notes/ai-log.md    raw log of the build: prompts, mistakes, decisions
```

Also see `PROMPTS.md`, `AI-NOTES.md` and `TRADEOFFS.md`.
