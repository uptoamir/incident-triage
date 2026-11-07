# AI notes

## How I used AI

| Stage | What the AI did | What I did |
|---|---|---|
| Planning | Four agents planned independently. Claude Code compared them, two more agents reviewed all four, Claude merged, and the same two reviewed the result. | Chose who to ask what, and when to stop. No plan was written by hand. |
| Build | Claude Code wrote the code phase by phase against `docs/PLAN.md` and `CLAUDE.md`, testing and running the real thing each phase. | Phases 0–1: Claude decided. From phase 2 on, it stopped at each phase with 2–3 decisions and measured options, and I made the call. One exception: I asked it to decide strict vs lenient mode. |
| Tests | Wrote them; the guardrail tests came before the code. Broke the code on purpose to check the important tests can fail. | Picked the bar: offline by default, live checks invariants only. |
| Review | A second model (Sonnet), cold, findings only. | Decided what to fix (all 13), and how. |
| Docs | Drafted from `notes/ai-log.md`. | Chose the framing: real time spent, prompt #1 verbatim, the diagram. |

## Where the AI got it wrong, and what caught it

1. **A timeout that wasn't there (phase 2).**
   - What went wrong: Claude wrote the LLM adapter with `httpx.Timeout`, from memory. The installed openai SDK is v3, which runs on `httpx2`. The timeout didn't raise; it quietly turned into a broken object, so the 20 s timeout the brief asks for wasn't really there.
   - How it was caught: the fake-transport tests failed on the httpx / httpx2 mismatch, and a look at the installed SDK confirmed it.
   - The fix: `openai.Timeout`, plus a test that checks the client's actual timeout values.
2. **Guardrails with holes, and a test that encoded the bug (phase 6).**
   - What went wrong: the guardrails only scanned four fields. An invented second quote, a clarifying question, or an ID with a lookalike dash (`INC‑99999`) could carry an uncited incident ID into the answer. One of Claude's own tests asserted the leaky behavior. Two other tests could never fail: the logging tests checked the fixture's own filter, not the app's, and the key canary matched the scrub regex by construction.
   - How it was caught: the independent Sonnet review.
   - The fix: one sanitizer over every string the model writes. The tests now scan the whole answer, and each new test was checked by breaking the code it protects.
3. **A test that looked fine but wasn't (phase 4).**
   - What went wrong: the two-ingests-at-once test only caught a broken transaction (plain `BEGIN` instead of `BEGIN IMMEDIATE`) in 3 of 5 runs.
   - How it was caught: breaking the code on purpose.
   - The fix: a barrier at the racy spot. Now it catches the bug 5 of 5 times.
4. **The plan was wrong, too.**
   - What went wrong: it assumed the SDK logs its retries where we'd see them. They're logged at DEBUG.
   - How it was caught: reading the installed SDK instead of trusting the plan.
   - The fix: a request hook that logs every attempt with the correlation ID.
5. **Before any code existed,** AI reviewers of AI plans found, and reproduced:
   - an ID regex that misses `INC-9999`
   - a `:memory:` test DB that's empty for every request
   - `tags=db&tags=db` returning nothing
   - `LLM_TEMPERATURE=none` crashing startup

The build-time mistakes were caught by the checks built into the workflow: tests, real runs, deliberate breaks, and a second model. I didn't catch them by reading diffs line by line. My part was setting that up and making the call on each finding.

## How I validated
- **Offline:** 131 tests (fake LLM, temp SQLite), plus ruff and format, before every commit.
- **Deliberate breaks:** mutation checks on the tests that matter most.
- **Real runs:** the server once per phase. That's how uvicorn's ANSI `color_message` turned up leaking into the JSON logs, which no test had caught.
- **Live, real model:** the 7 golden questions pass 7/7.
- **Measured before deciding:**
  - strict vs lenient: 0 of 16 quotes failed
  - recall: 15/20 with 8 candidates, 18/20 with 12
  - model speed
- **Secrets:** a check before every push that the API key isn't in any tracked file.

## Prompt patterns that worked
- **Several independent plans, then cross-review.** Different agents caught different bugs.
- **Give the AI files to cite:** a spec it references by section (`PLAN.md §7.2`), plus a house-rules file it reads every session.
- **Phase gates.** Stop, show 2–3 decisions with numbers, pick, commit.
- **Measure, don't guess:** recall, strict vs lenient, latency.
- **Break your tests on purpose.** A test that can't fail is worse than no test.
- **A cold review by a different model:** findings with file:line only, no edits.
- **Check the installed SDK, not the AI's memory of it.**

## Calls I made
- **Phase 2:** gpt-4o-mini as the default model, log every LLM attempt, declare httpx2 as a dev dependency.
- **Phase 3:** an exact 40/20/20/20 environment mix, golden clusters kept out of the random filler, keep the vague tickets.
- **Phase 4:** 12 candidates instead of 8.
- **Phase 5:** accept 5–8 s latency, leave the prompt as is.
- **Phase 6:** fix all 13 findings, keep the removed-ID audit trail, make the deadline a hard cap.
- **Docs:** state the real time spent, quote prompt #1 verbatim, the two-page diagram.

Strict mode was Claude's call, at my request. Full detail: `notes/ai-log.md`.
