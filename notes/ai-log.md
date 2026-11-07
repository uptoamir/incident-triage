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

Kickoff (summary, not verbatim): build from docs/PLAN.md phase by phase. At each phase Claude decides, tests, reviews its own diff against the plan, then commits. Keep this log honest.

### Phase 0: setup
- Repo, uv with Python 3.12 pinned. The system python3 here is 3.9.6, which is end-of-life.
- pyproject, Makefile, `.env.example`, CLAUDE.md house rules, PLAN.md, planning trail.
- Decided: the key lives only in the gitignored `.env`. Before every push, a check confirms the key string isn't in any tracked file.
- Decided: the take-home brief itself stays out of the repo, since it's the company's text. The plans refer to it by name.

### Phase 1: foundation
- Built settings, JSON logging, the correlation-ID middleware, the error envelope, the body-size limit, `/health`, and `python -m app`.
- Settings use `env_parse_none_str="none"` from the start, because review round 2 showed `LLM_TEMPERATURE=none` crashes otherwise. CF1 covers it.
- The correlation filter sits on the root *handler*, not a logger, so records propagating up from uvicorn and openai get the ID too. OB2 checks it.
- The middleware catches crashes itself, because Starlette's error middleware sits outside ours and its 500s would lose the header. OB3 checks it.
- 16 tests green on the first real run. Ruff flagged two long lines.
- **Caught by running the real server, not by the tests:** uvicorn sends a `color_message` copy of each log message full of ANSI color codes, and it was leaking into every JSON line. Dropped it and added a test. Lesson: green tests only cover what you thought to check, so do one real run per phase.
- Decided: no module-level `app` object. That would read `.env`, with the real key, at import time, including in tests. The app is built only through the factory: `python -m app` or `uvicorn --factory app.main:create_app`.
- Decided: the crash response is built inline in the middleware, so the observability layer doesn't import the api layer. A little duplication of the envelope shape, and OB3 pins it.
- Heads up: the lock resolved openai 3.46, Starlette 1.10, and FastAPI 0.162, all newer than the plan assumed. Check the SDK's real API before writing the adapter.
