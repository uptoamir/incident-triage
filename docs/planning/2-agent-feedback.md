# Feedback on the four incident-triage plans

| | |
|---|---|
| Reviewer | Agent 2, the author of `2.md`. Weigh my comments on `2.md` with that in mind. |
| Date | 2026-11-06 |
| Reviewed | `1.md`, `2.md`, `3.md`, `4.md`, against `incident-triage-take-home.md` |
| Method | Read all four plans in full. Checked the machine they will run on. Reproduced three suspected bugs with small SQLite and regex checks (evidence at the end). |

---

## Verdict

All four plans cover every requirement in the brief. **4.md is the strongest base.** 2.md and 3.md are close behind with different strengths. 1.md is the leanest and quickest to build, but it is the weakest on "don't invent details".

They share the same core choices:
- FastAPI and SQLite full-text search (FTS5)
- ingest that hashes each record to decide add / update / skip
- `/assist` reusing the `/search` function
- grounding checks in code
- no LLM call when search finds nothing

So the differences below are about details, not direction.

---

## Side by side

| | 1.md | 2.md (mine) | 3.md | 4.md |
|---|---|---|---|---|
| Length | 609 lines | 959 | 741 | 993 |
| Checked this Mac first | yes | no | no | yes |
| Text search | all words, then any word if nothing matches | any word | any word | any word |
| LLM output | plain JSON mode + one retry | strict schema only | strict + fallback + retry | strict + fallback |
| Checking the model's quotes | lenient, first thing cut | strict, never cut | strict, cut if running late | strict, never cut |
| Extra grounding | none | none | none | checks codes, versions and numbers; "partial" status; human-review flag |
| Test questions with expected answers | no | no | yes, generated | yes, golden list |
| Plan for using AI tools | good | strong | good | strongest |

"Checking the model's quotes": the model must copy a short phrase from each incident it cites, and code confirms the phrase really is in that record. Strict mode drops an incident whose quote doesn't check out; lenient mode keeps it with a flag.

---

## Bugs confirmed by running checks

### 1. 3.md: the test database is `:memory:`, but each request opens a new connection
- **Where:** §10 sets `DB_PATH` to `:memory:` in tests. §11 opens one SQLite connection per request.
- **Problem:** every connection to `:memory:` gets its own empty database, so data written through one connection is invisible to the next. Tests fail with "no such table". This also contradicts 3.md's own §12.2, which says integration tests use a temp SQLite file.
- **Fix:** use a temporary file (`tmp_path`) in tests, as the other three plans do.

### 2. 4.md: the "invented specifics" check (G5) also matches incident IDs
- **Where:** in §8.4, guardrail G5 scans `why_relevant`, next steps and the draft for error codes using the pattern `[A-Z]{2,}-\d+`. In §8.3, prompt rule 4 tells the model to cite `[INC-xxxxx]` inline in `why_relevant`.
- **Problem:** `INC-00042` matches the error-code pattern. Unless the record's `id` field is part of the text G5 searches (the plan doesn't say), strict mode drops the citations the brief requires.
- **Fix:** exclude the incident-ID pattern from G5. The ID allow-list (G1, G2) already covers IDs.

### 3. All four plans: a repeated tag in the filter returns nothing
- **Where:** the "has all tags" filter in 1.md §4.3, 2.md §9.2, 3.md §5.4 and 4.md §6.2. Each compares a count against the number of tags supplied.
- **Problem:** `tags=db&tags=db` asks for 2 distinct tags, but only one exists, so nothing matches. 3.md's `COUNT(*)` version gives the same result.
- **Fix:** remove duplicate filter values before building the query.

---

## Other problems (found by reading; not run)

- **2.md and 3.md don't account for this machine's Python.**
  - `python3` here is 3.9.6, which is end-of-life (October 2025). It fails on `X | None` type hints, which Pydantic evaluates at import time.
  - 2.md asks for Python ≥ 3.11, but its quickstart only says "venv". 3.md's setup is `python -m venv`. Both would pick up 3.9.6.
  - 1.md (§0) and 4.md (§0) checked the machine and use uv with Python 3.12 or 3.13.
- **1.md and 4.md don't lock the database at the start of ingest.**
  - Both read the stored hashes and then write in an ordinary transaction (1.md §5, 4.md §5.2).
  - Two ingests running at once can both read "not stored yet" and collide. One fails with "database is locked" or a duplicate-key error instead of waiting its turn.
  - 2.md (§8) and 3.md (§5.2) start the transaction with `BEGIN IMMEDIATE`, which avoids this.
- **1.md lets an env var switch on the fake LLM** (`LLM_PROVIDER=fake`, §1 D4 and §9). It's labelled tests-only, but reviewers may read it as breaking "must call a real LLM at runtime". 3.md (§8.1) and 4.md (§13) keep the fake inside the tests.
- **3.md mixes an async LLM client with sync SQLite and never picks one model** (§8.1–8.2 vs. §11). Its own watchlist warns about blocking calls inside async handlers. The other three are sync throughout.
- **2.md overstates strict JSON-schema output** as "the most widely supported option" (§11). It isn't: support varies by model and Azure API version. The other three all have a plain JSON-mode option. 1.md and 3.md also retry once on bad output; 4.md defers that retry. 2.md needs both.
- **1.md and 4.md default to `gpt-4o-mini`** (1.md §9, 4.md §10). Check it's still offered before relying on it.
- **4.md has the biggest scope:** 28 unit tests, 6 integration tests, two guardrail modes and an eval script (§13). It only fits in 3 hours if its feature freeze at 2:25 (§16) is respected.
- **4.md installs with `uv pip install`** (§15.1) while committing a `uv.lock` (§3.3). `uv pip install` ignores the lockfile; use `uv sync`.

---

## Worth taking from each plan

- **1.md**
  - Search tries all words first, falls back to any word, and reports which mode it used (D13). `/search` gets precise totals, and natural-language `/assist` questions still find candidates.
  - A reduced scope for when only 1 hour is available (§12).
- **2.md**
  - Reject unknown query parameters (§9.3). Otherwise a typo like `env=prod` is silently ignored and the user thinks a filter was applied.
  - The SQLite transaction details (§7–§8), and the warning that the OpenAI SDK's default timeout is 10 minutes (§11).
- **3.md**
  - The generator writes the expected incident IDs for each scenario (`ground_truth.json`, §4.2), so nobody maintains that list by hand.
  - The SDK's built-in retries are off, and the app runs its own logged retries under one overall `/assist` deadline (§8.3).
  - The first planned prompt asks the AI to critique the plan (§14).
- **4.md**
  - A `CLAUDE.md` of house rules the AI reads on every prompt (§14.2). It also counts as a documented prompt.
  - A second model as an independent reviewer (§14.1).
  - A prompt-injection ticket planted in the dataset (§4.3).
  - A test that checks the API key never shows up in logs or responses (LL3, §13.1).
  - A C# / ASP.NET Core appendix, since the brief allows C#.

---

## Recommendation

Build from 4.md and make these changes:
1. Exclude incident IDs from the G5 error-code check.
2. Start ingest with `BEGIN IMMEDIATE`.
3. Remove duplicate filter values.
4. Have the generator write the expected IDs for the golden questions, as 3.md does.
5. Add 1.md's retry on bad model output now, instead of deferring it.
6. Install with `uv sync` so the lockfile is used.

Then run 4.md's strict guardrails on the live golden questions early. If they throw away too much good output, switch to lenient mode.

---

## A note on 4.md's author line

4.md is written as if by "Senior Staff Software Engineer, Dayforce". It uses payroll-style sample data (`payroll-engine`, `timesheet-api`, …) and has a section on hardening a multi-tenant HCM SaaS. If Dayforce is who you're interviewing with, that tailoring helps. Either way, keep the "Author" line out of anything you submit.

---

## Evidence

**This machine**

| Check | Result |
|---|---|
| `python3` (`/usr/bin/python3`) | 3.9.6 |
| Homebrew Pythons | 3.11.13, 3.12.10, 3.13.11 |
| uv | 0.11.7, with a uv-managed CPython 3.13.14 |
| SQLite in the system Python | 3.51.0. An FTS5 table with `porter unicode61 remove_diacritics 2` creates without error. |

**Bug checks** (throwaway Python, run with `python3 -I`)

| Check | Output |
|---|---|
| Create a table on one `:memory:` connection, then query it from a second | `no such table: incidents` |
| `re.findall(r'[A-Z]{2,}-\d+', 'Same symptom on payroll-engine [INC-00042], error ERR-5003')` | `['INC-00042', 'ERR-5003']` |
| "Has all tags" query with `tags=['db','db']` against an incident tagged `db` and `timeout` | Count compared with 2: no rows. Count compared with 1 (after removing the duplicate): the incident matches. |
