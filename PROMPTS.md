# Prompts

The prompts that shaped this repo, copied verbatim (only my home path is shortened to `~`). The full raw log, including what broke and who decided what, is in `notes/ai-log.md`.

---

**Prompt #1: plan from the brief**

* Tool used: Claude Code (Opus)
* Goal: a full plan before any code, with decisions, tests, and the AI workflow written down
* Prompt (copy/paste):

    ```
    you are senior staff software engineer at Dayforce and here is your task ~/Interview/incident-triage-take-home.md . don't code anything just document your plan and details in 4.md plan file
    ```
* Result summary: a 990-line plan, `docs/planning/4.md`: architecture, decision records, test IDs, guardrails G1–G9, a CLAUDE.md idea, a timeline with a cut list.
* What you kept: the core design. That's SQLite FTS5, a strict JSON schema, guardrails enforced in code rather than the prompt, incident facts taken from the DB, the `partial` status, and a prompt-injection ticket planted in the data.
* What you changed manually (and why): nothing by hand. I didn't trust one plan, so I got three more from separate agent sessions and had them cross-reviewed (prompts #2–#4). That found real bugs in this one.
* Any follow up prompt(s): #2
* Link to code/commit: `docs/planning/4.md`

---

**Prompt #2: compare the four plans**

* Tool used: Claude Code
* Goal: find the bugs and gaps in each plan before choosing a base
* Prompt (copy/paste):

    ```
    check these 4 plans
      ~/Interview/4.md
      ~/Interview/3.md
      ~/Interview/2.md
      ~/Interview/1.md
    ```
* Result summary: a ranking (2.md first, 4.md close behind) and concrete bugs:
  * 4.md's ID scan `INC-\d{5}` lets an invented `INC-9999` through.
  * 3.md's tests use `:memory:` with a connection per request, so every request sees an empty DB.
  * 1.md lets an env var switch on the fake LLM.
* What you kept: the bug list. It fed straight into the merge.
* What you changed manually (and why): its ranking didn't stand. The two independent reviewers both picked 4.md as the base, and the merge (#3) went with that.
* Any follow up prompt(s): two separate agents reviewed all four plans on their own: `docs/planning/1-agent-feedback.md` and `2-agent-feedback.md`.

---

**Prompt #3: merge, using the two independent reviews**

* Tool used: Claude Code
* Goal: one plan that fixes everything the three reviews found
* Prompt (copy/paste):

    ```
    read these 2 other agents feedback then write the 5.md . agent 1.md feedback ~/Interview/1-agent-feedback.md and agent 2.md feedback ~/Interview/2-agent-feedback.md
    ```
* Result summary: the merged plan. It's built on 4.md, with all 33 review points logged as fixed, deferred or rejected, and why. One example: a scope tier list, after both reviewers said the plan was too big for 3 hours.
* What you kept: all of it, then sent it back for another review round.
* What you changed manually (and why): nothing by hand.
* Any follow up prompt(s): #4

---

**Prompt #4: second review round on the merged plan**

* Tool used: Claude Code
* Goal: apply the two reviewers' feedback on the merged plan
* Prompt (copy/paste):

    ```
    agent 1 and 2 feedbacks on 5.md ~/Interview/1-agent-5-feedback.md and ~/Interview/2-agent-5-feedback.md
    ```
* Result summary: 23 more fixes, all small. The notable ones:
  * `LLM_TEMPERATURE=none`, the plan's own advice, crashed startup with plain pydantic-settings. A reviewer reproduced it.
  * The free-text ID check ran before the evidence check, so a dropped incident could still be named in the answer.
  * The first live LLM call moved from 1:05 to 0:20.
* What you kept: all of it. This became `docs/PLAN.md`.
* What you changed manually (and why): nothing by hand.
* Link to code/commit: `4fb5cce` (repo setup, plan and planning trail)

---

**Prompt #5: house rules every AI session reads**

* Tool used: Claude Code, via `CLAUDE.md` at the repo root
* Goal: stop the usual AI mistakes before they're written: f-string SQL, `INSERT OR REPLACE`, `:memory:` test DBs, missing timeouts, scope creep
* Prompt (copy/paste): see [`CLAUDE.md`](CLAUDE.md). It's short, and it's the exact text.
* Result summary: the build followed it. The one time Claude broke a rule (writing the query builder before its tests, in phase 4), the log says so, and the tests were checked by breaking the code on purpose.
* What you kept: as is.

---

**Prompt #6: a phase-gate decision (one example of many)**

* Tool used: Claude Code. From phase 2 on, it stopped at each phase with 2–3 decisions backed by measurements, and I picked.
* Goal: decide how to improve search recall for `/assist`
* Prompt (copy/paste). Claude's question, then my answer:

    ```
    Search finds 15 of the 20 golden incidents in the top 8 that /assist sends to the LLM. How should we improve recall?
    - Send 12 candidates (Recommended): Recall goes to 18/20 with no tuning. Costs about 50% more prompt tokens (roughly 3k to 4.5k) and still fits the 12k-character context budget.
    - Extend stopwords, keep 8: Recall goes to 16/20. Risk: the list gets tuned on the same 5 questions it's measured on (overfitting).
    - Keep 8 as is: 15/20. Record it as a known gap, with the eval script and tuning in "next 2 hours".

    > Send 12 candidates (Recommended)
    ```
* Result summary: `ASSIST_CANDIDATES` went from 8 to 12, and the change is recorded in PLAN.md's "Changes during the build" table.
* What you kept: the measured option. I rejected stopword tuning because it would overfit to our own 5 questions.
* Link to code/commit: `89af41b`

---

**Prompt #7: independent code review by a second model**

* Tool used: a fresh Claude Code subagent on Sonnet, with no context from the build. Claude Code wrote this prompt as the plan's review step.
* Goal: an adversarial review: findings only, nothing edited
* Prompt (copy/paste):

    ```
    You're reviewing a take-home repo at ~/Interview/incident-triage as a strict senior reviewer. It's a FastAPI service over ~300 synthetic incident tickets: SQLite FTS5 search, idempotent ingest, and POST /assist, which retrieves candidates through the same search code path and calls a real LLM (OpenAI SDK v3, which runs on httpx2) under hard grounding rules: it must cite incident IDs, must not invent incident details, says so when nothing relevant is found, and returns clear errors when the LLM fails. Every log line must carry a correlation_id.

    The spec is docs/PLAN.md (long; §9 is /assist and its guardrails, §10 observability, §12 limits, §13 tests, plus a "Changes during the build" table at the end). House rules for AI-written code are in CLAUDE.md.

    Rules for you:
    - Do NOT edit, create or delete any files in the repo.
    - Do NOT read .env, and do not print or search for API keys. Do not run `make test-live`, `make smoke`, `make run`, or anything that calls the real LLM or the network.
    - You may run: `uv run pytest -q` and `uv run ruff check .` from the repo root.

    Report only concrete issues, each with: file:line, what's wrong, why it matters (a concrete failing input or scenario), and a suggested fix. Check specifically:
    1. Any path where /assist can return an incident ID that wasn't retrieved, or an incident detail that isn't in the stored records (app/assist/guardrails.py, app/assist/service.py).
    2. SQL or FTS5 strings built from user input (app/search/).
    3. External calls without an explicit timeout.
    4. Broad excepts that hide failures, or error paths that return 200.
    5. Log lines that can lack correlation_id; secrets or full prompts in logs or responses.
    6. Imports that break the layering (services importing app/api or FastAPI).
    7. Tests that need the network, mock the unit under test, or can't actually fail.
    8. Anything docs/PLAN.md marks P0 that's missing or behaves differently from the spec.

    Rank findings by severity (high / medium / low). At most 15. Skip style nits and anything ruff already enforces. If you think something is fine after checking, don't list it. End with one line: the single change you'd make first.
    ```
* Result summary: 14 findings, several reproduced with scratch mutations. 13 were real; the 14th, missing docs, was just the next phase. The worst: uncited incident IDs could reach the answer through three paths my tests never looked at.
* What you kept: fixes for all 13 (my call). I kept the removed-ID list in the response as an audit trail (my call), and made the deadline a hard cap (my call).
* Link to code/commit: `7e7df18`

---

**Prompt #8: the other agents (plans 1–3 and the two reviewers)**

* Tool used: separate agent sessions
* Prompt (copy/paste): TODO, paste from those sessions. Their output is in `docs/planning/`.
