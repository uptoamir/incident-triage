# Review of the four plans (1.md, 2.md, 3.md, 4.md)

Reviewed: 2026-11-06 · Against: `incident-triage-take-home.md` · Reviewer: Claude (Fable 5.1), which also wrote 1.md earlier in the same session, so 1.md was reviewed at least as hard as the others.

---

## 1. Verdict

All four plans converge on the same architecture:

- FastAPI + Pydantic v2
- SQLite FTS5 with bm25 ranking and `snippet()`
- the `openai` SDK for OpenAI and Azure OpenAI
- hash-based idempotent ingest in one transaction
- a zero-hit short circuit in `/assist` that never calls the LLM
- code-level guardrails after the LLM call (ID allow-list, evidence check, ID scrub)
- a pure ASGI correlation-ID middleware plus a logging filter
- an in-memory, bounded trace store behind `GET /debug/trace/{id}`

The differences are depth and a handful of engineering details.

| Plan | One-line assessment |
|---|---|
| **4.md** | Strongest spec. Decision records, test IDs, `CLAUDE.md` house rules, facts joined from the DB, `partial` status, cut list. Over-scoped for 3 h unless the cut list is applied early. |
| **2.md** | Close second. Catches several gotchas the others miss (handler-level log filter, `ServerErrorMiddleware`, strict-schema keyword limits, models that reject `temperature`). Largest P0 tier of the four. |
| **3.md** | Solid, but two internal contradictions (async LLM client vs sync SQLite; `:memory:` DB with per-request connections). |
| **1.md** | Most realistic for 3 h. Misses safeguards the others caught and exposes a runtime fake LLM provider. |

---

## 2. Side-by-side comparison

| Dimension | 1.md | 2.md | 3.md | 4.md |
|---|---|---|---|---|
| Length | 609 lines | 959 | 741 | 993 |
| LLM output format | JSON mode + repair retry | strict JSON schema | strict schema, JSON-mode fallback | strict schema, `LLM_JSON_MODE` fallback flag |
| Evidence-quote check default | flag only (lenient) | strict, lenient option | strict (drop) | strict, lenient option |
| `BEGIN IMMEDIATE` for ingest | no | yes | yes | no |
| 500 responses keep the correlation header | not handled | yes (middleware catches) | not handled | yes (middleware catches) |
| Log filter pinned to root handler | unspecified | yes, with the reason | yes | yes |
| Test that assist candidates equal `/search` results | no | yes | no | yes |
| Prompt-injection fixture | no | yes (fixture file) | yes (FakeLLM test) | yes (planted in dataset) |
| Fake LLM reachable at runtime | yes, `LLM_PROVIDER=fake` | no | no | no |
| Golden questions / ground truth | no | 5 demo questions | `ground_truth.json` | `GOLDEN.md` |
| `q` on `/search` | optional | optional | optional | required (literal reading of the brief) |
| Search semantics | AND, then OR fallback | OR default, `match=all` later | OR | OR, AND-first listed as +2 h |
| Realism for a 3-hour box | good | over-scoped | fair | over-scoped |

---

## 3. Problems per plan

### 1.md

1. **Runtime fake provider.** `LLM_PROVIDER=fake` is selectable through the environment, which weakens the "must call a real LLM at runtime" requirement. Keep the fake in `tests/` only and inject it through FastAPI dependency overrides.
2. **No `BEGIN IMMEDIATE`.** Ingest uses a plain transaction. In WAL mode two concurrent ingests can fail with a stale-snapshot "database is locked" error instead of serialising. Plans 2 and 3 get this right.
3. **Correlation filter placement unspecified.** The filter must be attached to the root handler, not a logger, or records propagated from `uvicorn`, `httpx` and `openai` loggers will not carry the ID.
4. **500 responses lose the header.** Starlette's `ServerErrorMiddleware` sits outside user middleware. The correlation middleware must catch unhandled exceptions itself and build the 500 envelope.
5. **Lenient evidence check by default.** Keeping a citation with `evidence_verified=false` is the weakest default of the four for a hard grounding rule. Strict with a lenient option, as in plans 2 and 4, is more defensible.
6. **Loose ends.** The request field `top_k` is defined and never used. README examples assume `jq` is installed; plan 4's `python -m json.tool` note is the safer choice.
7. **Missing tests the others have.** No equivalence test that `/assist` candidates equal `GET /search?q=<question>&limit=8`, and no prompt-injection fixture.

### 2.md

1. **Largest P0 tier.** G1 to G9 including evidence verification, eight test files, `demo.sh`, unknown-query-parameter rejection, uvicorn log routing, and a 15-minute bootstrap that already includes passing correlation tests. The cut order in §19 is the only thing keeping this inside 3 h. Apply it at the first slip, not at the 2:10 checkpoint.
2. **`LLM_MODEL` has no default.** One more variable to set correctly before `/assist` works. Put a working default in `.env.example` and in `Settings`.
3. **Prompts reference "2.md §5".** The plan needs a stable name in the repository (for example `PLAN.md`) before those prompts are pasted into PROMPTS.md.
4. **Query length mismatch** (shared, see §4): `q` ≤ 256 but `question` ≤ 1000.
5. Everything else checks out. The notes on handler-level filters (§12), `ServerErrorMiddleware` (§12), strict-mode schema keywords (§10.4), `max_completion_tokens` and models that reject `temperature` (§11), and FastAPI ≥ 0.115 query-parameter models with `extra="forbid"` (§9.3) are all correct, and the other three plans lack most of them.

### 3.md

1. **Async vs sync contradiction.** §8.1 defines `async def complete_json` on `AsyncOpenAI`, but SQLite access is sync and the plan never says whether handlers are `async def`. If they are, every SQLite call blocks the event loop, which the plan's own watchlist (§14) forbids. Decide: sync handlers plus the sync SDK (simplest), or async handlers with SQLite calls pushed into the threadpool.
2. **`:memory:` in tests.** §10 says tests use `DB_PATH=:memory:`, but §11 says one connection per request. Each `:memory:` connection is its own empty database, so the second request sees no tables. Use a `tmp_path` file, as plan 2 explicitly warns.
3. **Triggers chosen despite the plan's own warning.** §5.1 uses the external-content FTS5 pattern with AFTER INSERT/UPDATE/DELETE triggers while §14 lists trigger sync as an AI error hotspot. Plans 2 and 4 write the FTS row explicitly in the same transaction, which is easier to read and test.
4. **Hand-rolled retry loop.** `max_retries=0` on the SDK plus an own retry with jittered backoff plus an overall `ASSIST_DEADLINE_SECONDS` is more code than the SDK's built-in `max_retries=1`. Reasonable design, poor use of a 3-hour box.
5. **Data file missing maps to 500** (§6.1). A 503 with a `how_to_fix` hint matches the plan's own error philosophy better and is what plans 2 and 4 do.
6. **Minor.** Dataset is JSONL while the inline ingest body is a JSON array, so the loader must handle both formats.

### 4.md

1. **Over-scoped like plan 2.** 28 unit tests, 6 integration tests, a live test, `eval_assist.py`, G5, strict and lenient modes, streamed-body byte counting, `CLAUDE.md`, `GOLDEN.md`, 25 archetypes, and an appendix, in 180 minutes. The cut list in §16 is well ordered. Apply it early.
2. **G5 will drop good content in strict mode.** The scan for versions, error codes and numbers-with-units rejects legitimate paraphrases, for example a step that says "30 minutes" when the record says "30m". Run G5 in lenient mode or cut it, as the cut list already suggests.
3. **422 on a query with no searchable terms** (§6.1 step 4). `q=the` returning 422 is surprising. A 200 with `total: 0` and `terms: []` is friendlier and is what plan 2 does. Judgment call; document whichever is kept.
4. **Inaccurate rationale against `INSERT OR REPLACE`** (§5.2). The rowid-change argument does not apply to this schema, where `incidents_fts` is keyed on `incident_id`, not rowid. The valid reason is that REPLACE cannot distinguish updated from unchanged, so the counts would be wrong.
5. **No `BEGIN IMMEDIATE`.** Same concurrency note as plan 1.
6. **No repair retry for invalid JSON** (deferred to +2 h). Fine with strict schemas, but with the `json_object` fallback mode a single repair retry is cheap insurance.
7. **Strengths worth keeping:** D9 (facts joined from the database, never from the model), the `partial` status for 1–2 grounded incidents, test IDs that make traceability trivial, the `CLAUDE.md` house rules as a documented prompt, the planted injection ticket, the 5 % unresolved tickets, and the HCM-flavoured services if the interview is with that company.

---

## 4. Issues all four plans share

1. **Query length vs question length.** Every plan caps `q` lower than `question` (1.md 500/2000, 2.md 256/1000, 3.md 500/2000, 4.md 256/2000) and passes the question through the same search path. The `q` cap must live in the HTTP request schema only, never inside `SearchService`, or long questions will 422 inside `/assist`.
2. **Hardcoded `temperature=0`.** Only plan 2 notes that newer OpenAI reasoning models reject the `temperature` parameter with a 400. Make it optional and send it only when configured.
3. **Assist gets 45 to 50 minutes in every timeline** and is the riskiest part. Have the API key ready before starting and make the first live call as soon as the adapter exists, not at the end of the phase.
4. **`q` required or optional.** Plan 4 follows the brief literally ("`q` (text query)" with "optional filters"). The other three relax it to allow filter-only browsing. Either is fine if the README states it.
5. **All four promise to record only real AI mistakes for AI-NOTES.md.** Good. Keep the prompt log from the first prompt onward; reconstruction afterwards loses the "what I changed and why" detail that is being graded.

---

## 5. Recommendation

Build from **4.md** as the spec, trimmed to its "never cut" list plus G1 to G4 and G6 to G8. Then pull in:

- from **2.md**: `BEGIN IMMEDIATE` for ingest, the `temperature` note, the 200-on-no-terms behaviour, and the unknown-query-parameter rejection if FastAPI ≥ 0.115 is pinned;
- from **1.md**: the AND-then-OR search fallback (about ten lines; plan 4 defers it to the next two hours) and the simpler timeline as a realism check;
- from **3.md**: nothing structural; its `fallback.search_results` in LLM error bodies is already covered by plan 2's and plan 4's `retrieved_candidate_ids`.

Fix the shared query-length and `temperature` points in whichever plan is kept.
