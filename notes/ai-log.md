# AI log

Raw notes, written as the work happened. PROMPTS.md and AI-NOTES.md get pulled from here.
Home paths are shortened to `~`.

## Planning (no code)

Prompts I gave Claude Code (verbatim):

1. Plan (became 4.md; the other three plans came from separate agent sessions):
   > you are senior staff software engineer at Dayforce and here is your task ~/Interview/incident-triage-take-home.md . don't code anything just document your plan and details in 4.md plan file
2. Compare the four plans:
   > check these 4 plans ~/Interview/4.md ~/Interview/3.md ~/Interview/2.md ~/Interview/1.md
3. Merge, using two independent reviews of all four plans:
   > read these 2 other agents feedback then write the 5.md . agent 1.md feedback ~/Interview/1-agent-feedback.md and agent 2.md feedback ~/Interview/2-agent-feedback.md
4. Apply the second review round on the merged plan:
   > agent 1 and 2 feedbacks on 5.md ~/Interview/1-agent-5-feedback.md and ~/Interview/2-agent-5-feedback.md

Prompts for the other agents (plans 1–3 and the two reviewers): TODO, paste from those sessions.

What came out of it: see `docs/planning/README.md`. Short version: six real bugs found before any code, four of them reproduced with small checks.

## Build

Kickoff (summary, not verbatim): build from docs/PLAN.md phase by phase. Test, and review the diff against the plan, before every commit. Keep this log honest.

Who decides: Claude made the calls in phases 0–1. From phase 2 on, Claude stops at each phase with 2–3 decisions and a recommendation, and I make the call. Marked below as "Claude decided" vs "My call".

### Phase 0: setup
- Repo, uv with Python 3.12 pinned. The system python3 here is 3.9.6, which is end-of-life.
- pyproject, Makefile, `.env.example`, CLAUDE.md house rules, PLAN.md, planning trail.
- Claude decided: the key lives only in the gitignored `.env`. Before every push, a check confirms the key string isn't in any tracked file.
- Claude decided: the take-home brief itself stays out of the repo, since it's the company's text. The plans refer to it by name.

### Phase 1: foundation
- Built settings, JSON logging, the correlation-ID middleware, the error envelope, the body-size limit, `/health`, and `python -m app`.
- Settings use `env_parse_none_str="none"` from the start, because review round 2 showed `LLM_TEMPERATURE=none` crashes otherwise. CF1 covers it.
- The correlation filter sits on the root *handler*, not a logger, so records propagating up from uvicorn and openai get the ID too. OB2 checks it.
- The middleware catches crashes itself, because Starlette's error middleware sits outside ours and its 500s would lose the header. OB3 checks it.
- 16 tests green on the first real run. Ruff flagged two long lines.
- **Caught by running the real server, not by the tests:** uvicorn sends a `color_message` copy of each log message full of ANSI color codes, and it was leaking into every JSON line. Dropped it and added a test. Lesson: green tests only cover what you thought to check, so do one real run per phase.
- Claude decided: no module-level `app` object. That would read `.env`, with the real key, at import time, including in tests. The app is built only through the factory: `python -m app` or `uvicorn --factory app.main:create_app`.
- Claude decided: the crash response is built inline in the middleware, so the observability layer doesn't import the api layer. A little duplication of the envelope shape, and OB3 pins it.
- Heads up: the lock resolved openai 3.46, Starlette 1.10, and FastAPI 0.162, all newer than the plan assumed. Check the SDK's real API before writing the adapter.

### Phase 2: LLM adapter and first live call
- Built typed LLM errors, an OpenAI/Azure adapter, a factory with a "not configured" stand-in (the app still starts without a key, and /health says what's missing), and `make smoke` for one real call.
- Checked the installed SDK before writing the adapter: openai 3.46. `APITimeoutError` is a subclass of `APIConnectionError`, so the except order matters, or every timeout reports as "unavailable". There's a test for it.
- **Plan was wrong:** it assumed the SDK's retries show in our logs. They're logged at DEBUG. Added a request hook that logs every attempt at INFO with the correlation ID.
- **Caught by tests, biggest one so far:** SDK v3 runs on `httpx2`, not `httpx`. The adapter passed an `httpx.Timeout`, which didn't raise. It quietly became a broken timeout object, so the 20 s LLM timeout wasn't really applied. The fake-transport tests blew up on the httpx/httpx2 mismatch, and that's how it surfaced. Fixed with `openai.Timeout`, plus a regression test on the client's real timeout values.
- Test smell: the log-capture fixture only worked if an earlier test had set the root log level. Fixed it to set the level itself, and ran the file on its own to confirm.
- Ruff B008 on `Depends()` in a default argument: switched to `Annotated[..., Depends(...)]` instead of silencing the rule.
- Live calls: gpt-4o-mini OK (1.3 s, 11 output tokens). A bad key gives `llm_auth_failed` with the fix. gpt-5-mini rejects temperature 0, and our hint pointed straight at `LLM_TEMPERATURE=none`. With it off, gpt-5-mini took 2.7 s and 152 output tokens for the same call.
- My call: default model stays gpt-4o-mini. It's faster, cheaper, and takes temperature 0.
- My call: log every attempt via the hook, instead of DEBUG noise or our own retry loop.
- My call: declare httpx2 as a dev dependency, since the tests import it, and raise the openai floor to >=3.0 to match.

### Phase 3: data
- Built the `Incident` model, which does the normalizing: UTC timestamps, case for enums and services, and tags trimmed, deduped, and sorted. Also a seeded generator, `golden.json` built from the planted clusters, and a hand-written 12-record test fixture.
- Generator rules: one `random.Random(seed)`, and every choice goes through `rng.random()`, since Python only promises that stays the same across versions. Two runs are byte-identical, and DG1 also checks the output against the committed file.
- **Caught by reading the output, not the tests:** a sample said "Starting 5:00 UTC". The template wasn't zero-padding the hour. Fixed.
- **Looked like a bug, wasn't:** the environment mix came out 36/28/23/13 against a plan of 40/20/20/20. Checked the weighted pick over 100k draws (40/20/20/20) and spied on the filler loop's draws (they match the output). So the code was fine; it's just how seed 42 lands on 280 draws. Turned it into a decision instead of a "fix".
- Claude decided: service names are lowercased on ingest (`Payroll-Engine` becomes `payroll-engine`) rather than rejected. Flagged it for me to overrule.
- Ruff E501 on the generator's template strings: added a per-file ignore in pyproject, where it's visible, instead of wrapping the templates.
- My call: exact 40/20/20/20 environment mix. The exact list gets shuffled by the seeded RNG, so it's still deterministic. A test pins it.
- My call: keep the 5 planted clusters out of the random filler, so `golden.json` lists every relevant incident and recall numbers mean what they say.
- My call: keep the vague "needs triage" tickets. Real data has them, and they test that the assistant doesn't invent a fix.

### Phase 4: store, ingest, search
- Built the SQLite schema (with a standalone FTS5 table written in the same transaction as the row, no triggers), idempotent ingest under `BEGIN IMMEDIATE`, pure `terms.extract` and `query_builder.build`, the search service with `match=auto|all|any`, and the `/ingest`, `/search`, and `/incidents/{id}` routes. `/health` now reports the DB, the incident count, and FTS5.
- **I broke our own tests-first rule here:** wrote `terms` and `query_builder` before QB1–QB6. To make up for it, I mutated the code to check the tests can fail. Removing the tag dedupe fails QB4. A naive split-on-spaces tokenizer fails QB1, QB2, and QB6. Bonus finding: with the naive tokenizer, the "real FTS5 accepts it" tests still passed, because `fts_literal`'s quote-doubling held on its own. The second layer works independently.
- **Caught a flaky test by mutating the code:** swapping `BEGIN IMMEDIATE` for plain `BEGIN`, the original two-ingests-at-once test failed only 3 of 5 runs, because it depended on thread timing. A test that catches a bug 60% of the time gives false confidence. Rewrote it with a barrier at the racy spot, right after reading the stored hashes. Now plain `BEGIN` fails 5/5 with `database is locked`, and the real code passes 5/5.
- Self-review before running, two catches: an `__import__("json")` hack in the search service, and `too_many_records` raising the base error, which would have returned a 500 instead of a 422. Added `InvalidRequest`.
- The upsert's SET clause was a long hand-typed string. Now it's generated from a column tuple, which also makes "ingested_at is never overwritten" explicit.
- Ran `ruff format` once over the repo instead of fixing long lines by hand.
- Real run, 300 records: first ingest 300 new in 28 ms, second 300 skipped in 4.5 ms. All 27 log lines carry `correlation_id`. The sourdough question gets 0 hits, so the LLM is never called. The injection question does retrieve the planted injection ticket, so the guardrails will have to hold.
- Measured recall on golden.json (5 questions, 4 expected incidents each): 15/20 in the top 8. Tried two fixes on the same set: 12 candidates gave 18/20, and +20 generic stopwords gave 16/20 at 8 (but 17/20 at 12, and it risks overfitting to those 5 questions).
- My call: send 12 candidates to the LLM instead of 8. The prompt gets about 50% more tokens, and it still fits the context budget.
- Recorded this and the earlier plan changes in a "Changes during the build" table at the end of PLAN.md, so the spec stays true.

### Phase 5: /assist
- Built:
  - a trace recorder and store
  - the strict output schema, generated from pydantic
  - the `assist-v1` prompt
  - a context builder with truncation, a character budget, and blocks a record can't break out of
  - guardrails as pure functions
  - `AssistService`: no LLM call on zero hits, one repair attempt within the deadline, retrieved candidates attached to every LLM error
  - `/assist` and `/debug/trace/{id}`
- `/search` and `/ingest` now record trace steps too.
- **Tests first, for real this time:** wrote GR1–GR8 before `guardrails.py` existed, and collection failed on the missing module. Then implemented it, and all 8 pass.
- Mutation-checked four guardrails, and each break was caught by the test aimed at it:
  - G3 checking the *retrieved* set instead of the *kept* set (the exact round-2 review bug): GR2 fails.
  - Ignoring the model's "nothing relevant" flag: GR6 fails.
  - Accepting 1-word quotes: GR4 fails.
  - Leaving IDs in the customer draft: GR2 and GR7 fail.
- **Layering slip caught in review:** `AssistService` imported `FilterFields` from the API layer, which breaks the rule that services don't depend on `api/`. Moved the filter summary onto the plain `SearchFilters` dataclass, which also removed two helper methods.
- My scratch script for the live comparison failed at first: it couldn't import `app` from outside the repo. Ran it with `PYTHONPATH=.`.
- **Live golden run** (real gpt-4o-mini, 300 records): 7/7 golden questions keep every invariant. That means no invented IDs, no IDs in the customer draft, the nonsense question short-circuits, and INC-99999 never appears for the injection question.
- Strict vs lenient across 14 live calls: 0 of 16 cited incidents had a quote that failed verification.
- The model cited 13/20 planted matches, while search gave it 18/20. It tends to skip the stage and qa copies of a prod problem.
- 5–8 s per call, about 400–600 output and 2.2–2.6k input tokens.
- Same question, two runs, temperature 0: `ok` with 3 cited once, `partial` with 2 the next. That's why offline tests use the fake, and the live test checks invariants only.
- Claude decided (I asked it to make this one): keep `GUARDRAIL_MODE=strict` as the default. On this data it costs nothing and keeps the guarantee.
- My call: accept 5–8 s per /assist call. Tightening output risks cut-off answers.
- My call: leave the prompt as is, rather than nudging it to cite more incidents. Picking fewer when unsure fits grounding-first, and tuning on 5 questions would overfit. Goes in TRADEOFFS.

### Phase 6: hardening and an independent review
- Added the missing limit tests: ingest record cap, question and `q` length, offset, tag count, unknown body keys, context budget, and a record trying to close its own `<incident>` block.
- **Independent review:** a second model (Sonnet), in a fresh session with no context from this one. Instructions: review against PLAN.md and CLAUDE.md, report file:line findings only, edit nothing, never read `.env` or call the LLM. It came back with 14 findings, several reproduced with scratch mutations. I checked each against the code: 13 were real, and the 14th (docs missing) was just the next phase.
- **The serious one:** model-written text could still carry an uncited incident ID into the answer, in three ways:
  - an invented second evidence quote, which shipped flagged because the first quote verified
  - clarifying questions, which were never scanned
  - an ID written with a lookalike Unicode dash, `INC‑99999` (U+2011)
- And my own GR4 test literally asserted the first behavior, so the test had encoded the bug.
- **Tests that couldn't fail:**
  - The logging tests used a fixture with its own filter, so they tested the filter class, not `setup_logging()`. Deleting the filter from the app left everything green.
  - The key-leak canary started with `sk-`, which the scrub regex matches by construction.
- **Smaller real bugs:**
  - Malformed provider responses became 500s. An empty usage block crashed the token sum *after* a successful, paid call.
  - `/health` could 500, and it returned 200 "degraded" on a broken DB.
  - An `INCIDENT_ID_PATTERN` with a capture group broke the scan, and a bad regex only failed at request time.
  - JSON-object mode never showed the model the schema.
  - `^...$` with `.match()` accepted a correlation ID ending in `\n`.
  - Some errors had an empty `how_to_fix`.
  - IDs that differ only by case could resolve to the wrong record.
  - `SEARCH_DEFAULT_LIMIT` was unused, the 32-character tag rule wasn't enforced on filters, and ignored ingest fields weren't counted.
- My call: keep `guardrails.dropped` as an audit trail of removed IDs, IDs only, and stop echoing model text in warnings.
- My call: make `ASSIST_DEADLINE_SECONDS` a hard cap. Each try gets remaining / (retries + 1), and the repair call has no SDK retry.
- My call: fix all 13 now.
- Fixes:
  - One sanitizer runs over every model-written string. It folds lookalike dashes, strips zero-width characters, catches IDs by the configured pattern plus an exact match on every retrieved ID, and in strict mode returns only verified quotes.
  - IDs resolve exactly first, and case-insensitively only when that's unambiguous.
  - Defensive response parsing, `usage or 0`, scrubbing of the exact configured key, provider failures logged once (scrubbed), and the schema shown in JSON-object mode.
  - Per-call timeout and retry overrides, the pattern validated at startup, `/health` returning 503 and logging the cause, `fullmatch`, and `how_to_fix` everywhere.
- **Proved the new tests can fail:**
  - Removing the dash folding fails GR9 in both modes.
  - Removing the exact-ID scan fails the any-shape-ID test.
  - Removing the filter from `setup_logging()` now fails the new wiring test, while the 12 old tests still pass, which was exactly the gap.
- Deadline: a fake-clock test checks the repair call gets 5 s with no retry after a 40 s first call, and that there's no repair call at all with only 1 s left.
- 131 offline tests pass. The live golden run against the real gpt-4o-mini, now with the stricter check over every model-written string, passes 7/7.

### Phase 7: docs
- README (exact commands, things worth trying, config, errors, layout), PROMPTS.md (7 real prompts verbatim, plus a slot for the other agents' prompts), AI-NOTES.md, TRADEOFFS.md, and a two-page draw.io: "first read" and "how it grew", one box per commit. Claude drafted them from this log.
- My call: quote prompt #1 verbatim, persona line included. PROMPTS.md has to be copy/paste, and editing it would misquote.
- My call: state the real time, about 2 h planning plus about 3 h build, so over the 1–3 h box, and say why: it went on the plan reviews and the code review.
- Correction (Nov 8): the times above were clock time, read off timestamps. Measured from the session logs, agents were actually working about 1 h 10 min during planning and about 1 h 25 min during the build: about 2.5 hours in total. TRADEOFFS now says so.
- My call: the diagram shows the first read plus how it grew, not just the architecture.
- AI-NOTES says plainly that the build mistakes were caught by the workflow's checks (tests, real runs, deliberate breaks, a second model), not by me reading diffs. My part was the setup and the calls.
