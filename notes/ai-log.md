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
