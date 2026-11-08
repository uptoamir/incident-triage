"""A visual tour of every incident-triage endpoint. Demo branch only, not part of the graded submission.

    make run   # the API, in one terminal
    make ui    # this app, in another: http://localhost:8501

It calls the real API over HTTP, so every panel shows real requests, responses and correlation ids.
"""

import json
import os
from pathlib import Path
from urllib.parse import quote

import streamlit as st
from api_client import ApiClient, Exchange
from render import envelope, exchange, http_badge, status_badge, trace_steps

ROOT = Path(__file__).resolve().parents[1]
ANY = "any"

st.set_page_config(page_title="incident-triage", layout="wide")
api = ApiClient(os.environ.get("API_URL", "http://127.0.0.1:8000"))
state = st.session_state
state.setdefault("history", [])
state.setdefault("records", {})
state.setdefault("error_results", {})


def call(method: str, path: str, **kwargs) -> Exchange:
    ex = api.request(method, path, **kwargs)
    state.history.insert(0, ex)
    del state.history[30:]
    return ex


@st.cache_data
def dataset_choices() -> tuple[list[str], list[str]]:
    try:
        records = json.loads((ROOT / "data/incidents.json").read_text(encoding="utf-8"))
    except OSError:
        return [], []
    return sorted({r["service"] for r in records}), sorted({t for r in records for t in r["tags"]})


@st.cache_data
def golden() -> list[dict]:
    try:
        return json.loads((ROOT / "data/golden.json").read_text(encoding="utf-8"))
    except OSError:
        return []


SERVICES, TAGS = dataset_choices()


def filter_inputs(prefix: str) -> dict:
    """The same filter model /search and /assist share."""
    c1, c2, c3 = st.columns(3)
    env = c1.selectbox("environment", [ANY, "dev", "qa", "stage", "prod"], key=f"{prefix}_env")
    service = c2.selectbox("service", [ANY, *SERVICES], key=f"{prefix}_service")
    severity = c3.selectbox("severity", [ANY, "SEV1", "SEV2", "SEV3", "SEV4"], key=f"{prefix}_sev")
    tags = st.multiselect("tags (the incident must have all of them)", TAGS, key=f"{prefix}_tags")
    filters = {"environment": env, "service": service, "severity": severity}
    filters = {k: v for k, v in filters.items() if v != ANY}
    if tags:
        filters["tags"] = tags
    return filters


def hit_meta(hit: dict) -> str:
    return (
        f"{hit['service']} · {hit['environment']} · {hit['severity']} · score {hit['score']} · "
        f"{hit['created_at']} · tags: {', '.join(hit['tags'])}"
    )


def incident_meta(inc: dict) -> str:
    return f"{inc['service']} · {inc['environment']} · {inc['severity']} · {inc['created_at']}"


def llm_meta(m: dict) -> str:
    return (
        f"{m['provider']} / {m['model']} · {m['prompt_version']} · attempts {m['attempts']} · "
        f"{m['latency_ms']} ms · tokens in {m['tokens']['input']} / out {m['tokens']['output']}"
    )


def record_view(rec: dict) -> None:
    st.markdown(f"#### {rec['id']} · {rec['title']}")
    st.markdown(
        f":blue-background[{rec['service']}] :violet-background[{rec['environment']}] "
        f":orange-background[{rec['severity']}] · created {rec['created_at']}"
    )
    st.markdown(f"**Description**  \n{rec['description']}")
    st.markdown(f"**Resolution**  \n{rec['resolution_summary']}")
    st.caption(
        f"tags: {', '.join(rec['tags'])} · ingested {rec['ingested_at']} · updated {rec['updated_at']}"
    )


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("incident-triage")
    st.caption(f"API at {api.base_url}")
    health = api.request("GET", "/health")
    if health.status is None:
        st.error("The API isn't reachable. Start it with `make run`, then reload this page.")
        st.stop()
    h = health.response
    st.markdown(f"Database: **{h['db']}** · FTS5: **{h['fts5']}**")
    st.metric("Incidents indexed", h["incident_count"] if h["incident_count"] is not None else "?")
    llm = h["llm"]
    if llm["configured"]:
        st.success(f"LLM: {llm['provider']} / {llm['model']}")
    else:
        st.warning(f"LLM not configured (missing {', '.join(llm['missing'])}). /assist will return 503.")
    if h["incident_count"] == 0:
        st.info("Nothing indexed yet: start with the Ingest tab.")
    # "Recent requests" is drawn at the end of the script, after the tabs have made their calls;
    # drawn here it lagged one click behind (seen in the browser, not by the tests)

tabs = st.tabs(["Overview", "Ingest", "Search", "Incident", "Assist", "Trace", "Errors & limits"])

# ---------------------------------------------------------------- overview
with tabs[0]:
    st.subheader("What each part of the brief looks like")
    st.markdown(
        """
| Brief | Where to see it |
|---|---|
| 200–500 incidents, generator with a fixed seed | 300 records in `data/incidents.json`; the **Search** filters list their services and tags |
| `POST /ingest` is idempotent and returns counts | **Ingest**: run it twice, then send the demo batch with bad records |
| `GET /search`: text, filters, top N, total | **Search**: presets show all-words matching, the any-word fallback, filters, and hostile input |
| `GET /incidents/{id}` | **Incident**, or "Full record" on any search result |
| `/assist` uses the same search path (`tool:search`) | **Assist**: "Replay the search" proves the candidates match |
| Cite incident ids, invent nothing | **Assist**: verified quotes, the guardrails panel, facts from the database |
| Nothing relevant: say so and ask for more | **Assist**: the sourdough preset, where the LLM is never called |
| Clear errors when the LLM fails | **Errors & limits**, and the sidebar when no key is set |
| `correlation_id` everywhere, plus a step log | Every panel shows its id; **Trace** shows each step |
| Validation, limits, useful errors | **Errors & limits**: one button per case |
"""
    )
    st.caption(
        "Every request panel shows the exact curl command (with its X-Correlation-ID) and the raw JSON. "
        "The API's own interactive docs are at /docs."
    )

# ---------------------------------------------------------------- ingest
DEMO_BATCH = [
    {
        "id": "DEMO-1",
        "created_at": "2026-05-01T10:00:00+02:00",
        "environment": "PROD",
        "service": "payroll-engine",
        "severity": "sev2",
        "title": "Demo: payroll export slow",
        "description": "Export took 40 minutes instead of 5.",
        "resolution_summary": "Added an index on pay_group_id.",
        "tags": ["Performance", "database", "database"],
        "owner": "someone",
    },
    {
        "id": "DEMO-2",
        "created_at": "2026-05-02T10:00:00Z",
        "environment": "prod",
        "service": "payroll-engine",
        "severity": "urgent",
        "title": "Demo: bad severity",
        "description": "x",
        "resolution_summary": "x",
        "tags": ["x"],
    },
    {"id": "DEMO-1", "note": "duplicate id in the same batch"},
    "not a JSON object",
]

with tabs[1]:
    st.subheader("POST /ingest")
    st.markdown(
        "Loads `data/incidents.json` into SQLite. Each record is validated, normalized "
        "(UTC times, lower-case enums, tags sorted and de-duplicated) and hashed, so a re-run only "
        "writes what changed. **Run it twice: the second run skips all 300.**"
    )
    c1, c2 = st.columns(2)
    if c1.button("Ingest the data file", type="primary", key="ingest_file"):
        state.ingest_ex = call("POST", "/ingest")
    batch_text = st.text_area(
        "Or send your own records (this demo batch has an unknown field, a bad severity, a duplicate id "
        "and a non-object)",
        value=json.dumps(DEMO_BATCH, indent=2),
        height=280,
        key="ingest_batch",
    )
    if c2.button("Ingest the batch below", key="ingest_batch_btn"):
        try:
            state.ingest_ex = call("POST", "/ingest", json_body={"incidents": json.loads(batch_text)})
        except json.JSONDecodeError as exc:
            st.error(f"That isn't valid JSON: {exc}")
    if ex := state.get("ingest_ex"):
        if ex.ok:
            b = ex.response
            cols = st.columns(5)
            for col, key in zip(cols, ("received", "ingested", "updated", "skipped", "invalid"), strict=True):
                col.metric(key, b[key])
            st.caption(f"source {b['source']} · {b['duration_ms']} ms")
            if b["errors"]:
                st.markdown("**Rejected records** (the rest of the batch still went in)")
                st.dataframe(b["errors"], hide_index=True)
            if b.get("ignored_fields"):
                st.info(f"Unknown fields ignored, not rejected: {b['ignored_fields']}")
        else:
            envelope(ex)
        exchange(ex)

# ---------------------------------------------------------------- search
SEARCH_PRESETS = {
    "all words match": {"q": "payroll timeout"},
    "no record has both words, so it falls back to any word": {"q": "certificate quokka"},
    "prod only, tagged database": {"q": "timeout", "environment": "prod", "tags": ["database"]},
    "hostile FTS syntax, still a 200": {"q": 'timeout" OR title:x* NEAR(a b) ^c'},
    "only filler words: 200 with a note": {"q": "the and why"},
}


def apply_search_preset() -> None:
    preset = SEARCH_PRESETS.get(state.get("search_preset") or "", {})
    state.s_q = preset.get("q", state.get("s_q", ""))
    state.s_env = preset.get("environment", ANY)
    state.s_service = ANY
    state.s_sev = ANY
    state.s_tags = [t for t in preset.get("tags", []) if t in TAGS]
    state.s_match = "auto"


with tabs[2]:
    st.subheader("GET /search")
    st.markdown(
        "Words become quoted FTS5 terms, so user text can't inject search syntax. Filters are bound "
        "parameters and results are ranked with BM25. `match=auto` tries all words first, then any word."
    )
    st.pills("Presets", list(SEARCH_PRESETS), key="search_preset", on_change=apply_search_preset)
    state.setdefault("s_q", "payroll timeout")
    with st.form("search_form"):
        q = st.text_input("q", key="s_q")
        filters = filter_inputs("s")
        c1, c2, c3 = st.columns(3)
        match = c1.radio("match", ["auto", "all", "any"], horizontal=True, key="s_match")
        limit = c2.slider("limit", 1, 50, 10, key="s_limit")
        offset = c3.number_input("offset", 0, 1000, 0, key="s_offset")
        submitted = st.form_submit_button("Search", type="primary")
    if submitted:
        params = {"q": q, "match": match, "limit": limit, "offset": int(offset), **filters}
        state.search_ex = call("GET", "/search", params=params)
    if ex := state.get("search_ex"):
        if ex.ok:
            b = ex.response
            c1, c2, c3 = st.columns(3)
            c1.metric("total hits", b["total"])
            c2.metric("match mode used", b["match_mode"])
            c3.metric("showing", f"{len(b['results'])} (offset {b['offset']})")
            st.caption(f"terms searched: {b['terms']} · filters: {b['filters'] or 'none'}")
            for note in b["notes"]:
                st.info(note)
            for hit in b["results"]:
                with st.container(border=True):
                    st.markdown(f"**{hit['id']}** · {hit['title']}")
                    st.caption(hit_meta(hit))
                    st.markdown(hit["snippet"])  # matched words come back wrapped in ** markers
                    if st.button("Full record", key=f"open_{hit['id']}"):
                        state.records[hit["id"]] = call("GET", f"/incidents/{quote(hit['id'], safe='')}")
                    if rec_ex := state.records.get(hit["id"]):
                        if rec_ex.ok:
                            record_view(rec_ex.response)
                        else:
                            envelope(rec_ex)
        else:
            envelope(ex)
        exchange(ex)

# ---------------------------------------------------------------- incident
with tabs[3]:
    st.subheader("GET /incidents/{id}")
    st.markdown("The full stored record, plus when it was first ingested and last updated.")
    incident_id = st.text_input("Incident id", value="INC-00004", key="inc_id")
    c1, c2, c3 = st.columns(3)
    if c1.button("Fetch", type="primary", key="inc_fetch"):
        state.incident_ex = call("GET", f"/incidents/{quote(incident_id, safe='')}")
    if c2.button("Unknown id → 404", key="inc_404"):
        state.incident_ex = call("GET", "/incidents/INC-99999")
    if c3.button("Malformed id → 422", key="inc_422"):
        state.incident_ex = call("GET", f"/incidents/{quote('bad id!', safe='')}")
    if ex := state.get("incident_ex"):
        if ex.ok:
            record_view(ex.response)
        else:
            envelope(ex)
        exchange(ex)

# ---------------------------------------------------------------- assist
ASSIST_PRESETS = {f"{g['kind']}: {g['question']}": g["question"] for g in golden()}
ASSIST_PRESETS["no searchable words: why is it so?"] = "why is it so?"


def apply_assist_preset() -> None:
    if question := ASSIST_PRESETS.get(state.get("assist_preset") or ""):
        state.a_q = question


with tabs[4]:
    st.subheader("POST /assist")
    st.markdown(
        "1. Runs `tool:search`: the same `SearchService` call as `/search`, with `match=any`.\n"
        "2. Skips the LLM completely if nothing matched.\n"
        "3. Otherwise sends the top results to the LLM with a strict JSON schema.\n"
        "4. Checks the answer in code:\n"
        "   - it can only cite incidents it was shown\n"
        "   - each one needs a word-for-word quote from its own record\n"
        "   - text may only mention cited incidents\n"
        "   - the server decides the status, and facts come from the database"
    )
    st.pills(
        "Golden questions and edge cases",
        list(ASSIST_PRESETS),
        key="assist_preset",
        on_change=apply_assist_preset,
    )
    state.setdefault("a_q", next(iter(ASSIST_PRESETS.values()), "payroll run timing out in prod"))
    question = st.text_area("question", key="a_q", height=90)
    with st.expander("Filters (the same model /search uses)"):
        assist_filters = filter_inputs("a")
    if st.button("Ask", type="primary", key="assist_ask"):
        with st.spinner("Searching, then asking the LLM (usually 5–15 s)..."):
            state.assist_ex = call(
                "POST", "/assist", json_body={"question": question, "filters": assist_filters}
            )
        state.pop("replay_ex", None)
        state.pop("assist_trace_ex", None)
    if ex := state.get("assist_ex"):
        if not ex.ok:
            envelope(ex)
        else:
            b = ex.response
            status_badge(b["status"])
            if b["message"]:
                st.info(b["message"])
            left, right = st.columns([2, 1])
            with left:
                if b["relevant_incidents"]:
                    st.markdown("#### Relevant incidents")
                for inc in b["relevant_incidents"]:
                    with st.container(border=True):
                        st.markdown(f"**{inc['id']}** · {inc['title']}")
                        st.caption(incident_meta(inc))
                        st.markdown(inc["why_relevant"])
                        for e in inc["evidence"]:
                            mark = ":green[✓ verified]" if e["verified"] else ":red[✗ not in the record]"
                            st.markdown(f"> {e['quote']}  \n{mark} · from `{e['field']}`")
                if b["next_steps"]:
                    st.markdown("#### Next steps")
                    for n, s in enumerate(b["next_steps"], start=1):
                        source = (
                            f"from {', '.join(s['source_ids'])}" if s["source_ids"] else "general triage step"
                        )
                        st.markdown(f"{n}. {s['step']}  \n:gray[{source}]")
                if b["customer_draft"]:
                    st.markdown("#### Customer draft")
                    st.info(b["customer_draft"]["text"])
                    st.badge("needs human review before sending", color="orange")
                    st.caption(f"based on: {', '.join(b['customer_draft']['based_on'])}")
                if b["clarifying_questions"]:
                    st.markdown("#### Clarifying questions")
                    for q_ in b["clarifying_questions"]:
                        st.markdown(f"- {q_}")
            with right:
                st.markdown("#### Guardrails")
                g = b.get("guardrails")
                if g is None:
                    st.caption("The LLM wasn't called, so there was nothing to check.")
                else:
                    st.caption(f"mode: {g['mode']}")
                    if not any(
                        g[k] for k in ("dropped", "warnings", "unverified_evidence", "unsupported_specifics")
                    ):
                        st.success("Nothing removed or flagged.")
                    for d in g["dropped"]:
                        st.warning(f"dropped {d['id']}: {d['reason']}")
                    for w in g["warnings"]:
                        st.caption(f"⚠️ {w}")
                    if g["unverified_evidence"]:
                        st.warning(f"unverified quotes: {g['unverified_evidence']}")
                    if g["unsupported_specifics"]:
                        st.warning(f"specifics not found in the sources: {g['unsupported_specifics']}")
                st.markdown("#### Retrieval (tool:search)")
                r = b["retrieval"]
                st.caption(f"terms: {r['terms']} · match {r['match_mode']} · {r['total_hits']} hits")
                st.markdown(
                    " ".join(f"**{c}**" if c in b["citations"] else f"`{c}`" for c in r["candidate_ids"])
                    or "no candidates"
                )
                st.caption("bold = cited in the answer")
                st.markdown("#### LLM")
                if b["llm"]:
                    st.caption(llm_meta(b["llm"]))
                else:
                    st.caption("Not called: nothing to ground an answer on.")
                c1, c2 = st.columns(2)
                if c1.button("Replay the search", key="assist_replay"):
                    params = {"q": question, "match": "any", "limit": max(len(r["candidate_ids"]), 1)}
                    state.replay_ex = call("GET", "/search", params={**params, **assist_filters})
                if c2.button("Show the trace", key="assist_trace"):
                    state.assist_trace_ex = call("GET", f"/debug/trace/{ex.correlation_id}")
                if rp := state.get("replay_ex"):
                    same = rp.ok and [h["id"] for h in rp.response["results"]] == r["candidate_ids"]
                    if same:
                        st.success("Same candidates as /assist: one search code path.")
                    else:
                        st.error("Different candidates from /assist.")
            if tr := state.get("assist_trace_ex"):
                st.markdown("#### Trace of this request")
                if tr.ok:
                    trace_steps(tr.response)
                else:
                    envelope(tr)
        exchange(ex)

# ---------------------------------------------------------------- trace
with tabs[5]:
    st.subheader("GET /debug/trace/{correlation_id}")
    st.markdown(
        "Every request is logged as JSON lines that carry its correlation id, and its steps are kept "
        "in memory (the last 500 requests). Send `X-Correlation-ID` yourself, or use the one the API "
        "generated."
    )
    known = [ex.correlation_id for ex in state.history if ex.path in ("/assist", "/search", "/ingest")]
    trace_id = st.text_input("Correlation id", value=known[0] if known else "", key="trace_id")
    if st.button("Load trace", type="primary", key="trace_load") and trace_id:
        state.trace_ex = call("GET", f"/debug/trace/{quote(trace_id, safe='')}")
    if ex := state.get("trace_ex"):
        if ex.ok:
            trace_steps(ex.response)
        else:
            envelope(ex)
        exchange(ex)

# ---------------------------------------------------------------- errors & limits
ERROR_CASES = [
    ("Typo in a parameter name (env=prod)", "GET", "/search", {"q": "timeout", "env": "prod"}, None),
    ("Bad enum value (severity=urgent)", "GET", "/search", {"q": "timeout", "severity": "urgent"}, None),
    ("limit over the cap (51)", "GET", "/search", {"q": "timeout", "limit": 51}, None),
    ("Tag longer than 32 characters", "GET", "/search", {"q": "timeout", "tags": "x" * 40}, None),
    ("q missing", "GET", "/search", None, None),
    ("Unknown incident", "GET", "/incidents/INC-99999", None, None),
    ("Malformed incident id", "GET", f"/incidents/{quote('bad id!', safe='')}", None, None),
    ("Question too short", "POST", "/assist", None, {"question": "hi"}),
    (
        "Unknown filter name in /assist",
        "POST",
        "/assist",
        None,
        {"question": "payroll down", "filters": {"env": "prod"}},
    ),
    ("Unknown body key in /ingest", "POST", "/ingest", None, {"records": []}),
    ("Unknown trace id", "GET", "/debug/trace/no-such-trace", None, None),
    ("Unknown route", "GET", "/nope", None, None),
    ("Wrong method (GET /ingest)", "GET", "/ingest", None, None),
]

with tabs[6]:
    st.subheader("Errors and limits")
    st.markdown(
        "Every error has the same envelope: `code`, `message`, `how_to_fix`, `details`, `correlation_id`. "
        "Nothing returns a 500 or fails silently."
    )
    if st.button("Run every case", type="primary", key="errors_all"):
        for label, method, path, params, body in ERROR_CASES:
            state.error_results[label] = call(method, path, params=params, json_body=body)
    for label, method, path, params, body in ERROR_CASES:
        with st.container(border=True):
            c1, c2 = st.columns([3, 1])
            c1.markdown(f"**{label}**  \n`{method} {path}`")
            if c2.button("Run", key=f"err_{label}"):
                state.error_results[label] = call(method, path, params=params, json_body=body)
            if ex := state.error_results.get(label):
                c1.markdown(http_badge(ex))
                if ex.ok:
                    st.success("unexpected success")
                else:
                    envelope(ex)
    st.info(
        "LLM failures: restart the API with `LLM_API_KEY=` (empty) and ask the Assist tab anything that "
        "matches. You'll get a 503 `llm_not_configured` that names what to set and still lists what search "
        "found. `/search` keeps working."
    )

# ---------------------------------------------------------------- sidebar: recent requests
with st.sidebar:
    st.divider()
    st.subheader("Recent requests")
    for ex in state.history[:12]:
        st.markdown(f"{http_badge(ex)} `{ex.method} {ex.path}`  \n`{ex.correlation_id}`")
