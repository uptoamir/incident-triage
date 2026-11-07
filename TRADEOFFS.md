# Tradeoffs

## Time
About 2.5 hours of working time:

| Part | Time | What went into it |
|---|---|---|
| Planning | ~1 h 10 min (17:39–19:29 on the clock) | Four agents planned independently, then two rounds of review |
| Build | ~1 h 25 min (19:58–22:49 on the clock) | Includes a 20-minute independent code review and the fixes that came out of it |

Much of it went on review, on purpose: of the plans first, then of the code. Both found real bugs (see AI-NOTES.md).

## Done
- `POST /ingest`: idempotent, reports ingested / updated / skipped / invalid.
- `GET /search`: text plus filters, snippets, scores, and a total.
- `GET /incidents/{id}`: the full record.
- `POST /assist`:
  - search goes through the same code path, logged as `tool:search`
  - strict JSON from the LLM, with one repair attempt
  - guardrails in code
  - no LLM call when search finds nothing
  - clear errors when the LLM fails
- Correlation ID on every log line, plus step traces at `GET /debug/trace/{id}`.
- A seeded generator (300 incidents, byte-for-byte repeatable) and a golden question set.
- 131 offline tests, and a live test against the real LLM (7/7 passing).

## Guaranteed vs best effort
Guaranteed by code:
- Every incident in an answer was shown to the model and has a verified 3+ word quote from its own record (strict mode).
- Model-written text only mentions cited incidents.
- At most 5 incidents.
- Facts like titles, services and dates come from the database.
- No incident IDs in the customer draft.
- The status follows the evidence.
- When search finds nothing, the LLM is never called.

Best effort (the prompt, temperature 0, a warn-only check for invented numbers and codes, and human review of the draft):
- A false claim worded in plain language, with no ID, quote or specific value, can still get through.
- Nothing checks that a step doesn't invent a fix for an unresolved ticket.

## How I read the brief
- **No LLM call on zero hits.** There's nothing to ground an answer on, so the reply is fixed text asking for more info.
- **Fewer than 3 relevant incidents isn't padded out.** The answer comes back as `partial`, because padding would mean inventing relevance.
- **The customer draft has no incident IDs.** Its sources are listed in `based_on` instead.
- **Tag filters require all the given tags,** and `q` is required on `/search`.
- **Ingest adds and updates records. It never deletes.**

## Known issues and risks
- **Search quality:**
  - Search is lexical only, so synonyms are missed ("OOM" vs "out of memory").
  - On the golden set, search puts 18 of 20 expected incidents in the 12 it sends to the model, but the model only cites 13. It tends to skip the stage and qa copies of a prod problem. I left the prompt alone, because tuning it on 5 questions would overfit.
- **The model:**
  - Answers vary from run to run, even at temperature 0. The same question came back `ok` once and `partial` the next time.
  - `/assist` takes 5–8 s on gpt-4o-mini.
- **Operations:**
  - Traces live in memory, per process, and are lost on restart.
  - There's no auth on `/ingest` or `/debug/trace`, so turn debug off anywhere shared.
  - The deadline cap doesn't count the SDK's backoff between retries, so a request can run up to about a second over.

## Not done
- Authentication, rate limiting, and tenant isolation.
- Embeddings or hybrid search, and multi-value filters.
- Deleting records during ingest.
- Counting body bytes on streamed uploads.
- An automated eval script.
- Dockerfile and CI.

## Next 2 hours
- Turn golden.json into an eval script (recall@k, guardrail drop rate) and tune BM25 weights against it.
- A synonym and abbreviation map; keep `ERR-5003` together as a phrase.
- Date-range filters.
- Dockerfile and a CI workflow.

## Next 2 days
- **Search:** hybrid search (BM25 + embeddings, merged with reciprocal rank fusion) plus a re-ranker. A Postgres or OpenSearch adapter behind the same repository interface.
- **Quality:** an LLM-as-judge faithfulness check on the golden set in CI, gating prompt changes.
- **Operations:** OpenTelemetry in place of the in-memory traces; auth, rate limiting, PII redaction; an async client with streaming.
- **For a multi-tenant HR/payroll SaaS:** tenant isolation enforced by the server, data residency, and Azure OpenAI on private networking.
