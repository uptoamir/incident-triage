# Feedback on 5.md (the final plan)

| | |
|---|---|
| Reviewer | Agent 2, the author of `2.md` and `2-agent-feedback.md`. 5.md builds on that feedback, so weigh my view of how it was taken in with that in mind. |
| Date | 2026-11-06 |
| Reviewed | `5.md`, against `incident-triage-take-home.md` and the earlier feedback files |
| Method | Read 5.md in full. Re-checked the machine facts in its §1. Tested one config behaviour in a throwaway uv environment. Evidence is at the end. |

---

## Verdict

5.md is ready to build after a few small fixes. Every point from `2-agent-feedback.md` made it in (see 5.md §20), and the machine facts in §1 are correct. None of the fixes below change the design.

---

## Fix before you start

### 1. `LLM_TEMPERATURE=none` crashes startup (confirmed by running it)
- **Where:** §11 says "Set to `none` to stop sending it". §9.7's `llm_bad_request` hint gives the same advice.
- **Problem:** a plain `Optional[float]` setting rejects the string `"none"`. The app fails to start exactly when a user follows the documented advice.
- **Fix:** add `env_parse_none_str="none"` to the Settings `model_config` (or a field validator), and a config test for it.

### 2. The free-text ID scan runs too early, against the wrong set
- **Where:** §9.5.
  - G3 checks the IDs in `why_relevant`, next steps and the draft against the *retrieved* IDs.
  - The guardrails run in order, so G3 runs before G4 (evidence) and G6 (count) decide which incidents are kept.
  - G5 and `citations` use the *kept* set.
- **Problem:** a reason or step can still name an incident that G4 just dropped as unverified, or one the model never selected. That ID appears in the response but not in `citations`, which conflicts with "must cite the incident IDs used".
- **Fix:** run the text scan last, against the final kept IDs. Drop or scrub any other reference.

### 3. The model's `insufficient_context: true` is ignored
- **Where:** the output schema in §9.4 has the flag, but G6 sets the status from the number of kept incidents only.
- **Problem:** the model may say nothing is relevant but still list incidents. G6 then returns `ok` or `partial`, presenting incidents the model itself judged irrelevant.
- **Fix:** the flag may only make the status stricter. `true` always means `insufficient_context`.

### 4. Reproducing an assist search fails for long questions
- **Where:**
  - §8.2 caps `/search`'s `q` at 256 characters, while `/assist` accepts questions up to 2,000.
  - IT2 (§13.2) and README step 10 (§15.1) reproduce assist retrieval with `/search?q=<question>&match=any&limit=8`.
- **Problem:** for any question over 256 characters, that call returns 422.
- **Fix:** reproduce with the `terms` from the `tool:search` trace step. There are at most 16 of them, so in practice they fit the 256-character limit. Keep IT2's question under 256 characters.

### 5. Two section references in §8 are wrong
- **Where:**
  - The §8.1 status table says LLM failures are in "section 9.6"; they are in §9.7.
  - The §8.2 endpoints table says the `/assist` output is in "Section 9.7"; it is in §9.8.
- **Why it matters:** prompts will cite `docs/PLAN.md` sections, so a wrong reference points the AI at the wrong spec.

---

## Small stuff

- **Starting with the plain `uvicorn` command (§10.2).** That command sets up its own log handlers before `create_app()` runs. If those loggers are set to propagate without removing their handlers, every uvicorn line prints twice, and one copy has no correlation ID. Clear the handlers too, or state that `make run` is the only supported way to start. (Based on uvicorn's startup order; not run.)
- **One name for the lenient flag.** G4 says `evidence_verified: false`, but §9.8 and GR3 say `evidence.verified`.
- **One home for LLM errors.** §4.2 lists them in both `domain/errors.py` and `llm/base.py`.
- **Case-insensitive ID scan.** `\bINC-\d+\b` misses `inc-00042`.
- **Body limit vs. record limit (§11, §12).** 1,000 records at roughly 1 KB each is about the 1 MB body limit. So a large ingest can get a 413 before it reaches the 1,000-record limit. Raise `MAX_REQUEST_BYTES` to about 5 MB. (This is an estimate; the dataset doesn't exist yet.)
- **`notes/ai-log.md` (§4.2).** It sits in the repo but is marked "not a deliverable". Decide whether it is committed or gitignored.

---

## Advice

- **Trim `docs/PLAN.md`.** When you copy the plan in, drop §21 (interview prep) as well as the header table. Rehearsed answers look odd in a submission.
- **AI-NOTES.md examples.** The mistakes in §14.3 are real and usable, but AI agents caught all of them while reviewing other AI agents' plans. Make sure at least one example comes from the build itself and was caught by you, through a failing test, a curl, or your own review of a diff.
- **Tuning strict mode.** The schema allows one evidence quote per incident, so a single paraphrase drops it. If strict mode throws away too much in the live run, allow up to 2 quotes (any one verified is enough) before switching to lenient.

---

## Evidence

**Machine facts in 5.md §1, re-checked**

| Check | Result |
|---|---|
| `uv python find 3.12` | `/opt/homebrew/opt/python@3.12/bin/python3.12` (Homebrew 3.12.10, so nothing needs downloading) |
| SQLite in that Python | 3.51.3. An FTS5 table with `incident_id UNINDEXED` and `porter unicode61 remove_diacritics 2` creates without error. |
| git | 2.50.1 (Apple Git-155) |
| LLM environment variables | None of `OPENAI_*`, `AZURE_OPENAI_*` or `LLM_*` are set (only the names were checked, never values) |
| `make` | Present |

**Config check** (throwaway uv environment outside any project: pydantic 2.14.3, pydantic-settings 2.16.2, run with `LLM_TEMPERATURE=none`)

| Setting definition | Result |
|---|---|
| `llm_temperature: Optional[float] = 0` | Fails: `Input should be a valid number, unable to parse string as a number [type=float_parsing, input_value='none', input_type=str]` |
| The same, with `env_parse_none_str="none"` in the settings config | `llm_temperature=None` |
