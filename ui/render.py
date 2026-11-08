"""Streamlit pieces shared by the pages: the HTTP exchange viewer, the error envelope, the trace timeline."""

import streamlit as st
from api_client import Exchange

STATUS_COLORS = {"ok": "green", "partial": "orange", "insufficient_context": "gray"}


def http_badge(ex: Exchange) -> str:
    if ex.status is None:
        return ":gray-background[no response]"
    color = "green" if ex.status < 300 else "orange" if ex.status < 500 else "red"
    return f":{color}-background[{ex.status}]"


def exchange(ex: Exchange, label: str = "HTTP request and response") -> None:
    """The exact request (as curl, with its correlation id) and the raw JSON that came back."""
    with st.expander(
        f"{label}: {ex.method} {ex.path} → {ex.status or 'no response'} · {ex.elapsed_ms:.0f} ms"
    ):
        st.markdown(f"{http_badge(ex)} correlation id `{ex.correlation_id}`")
        st.code(ex.curl(), language="bash", wrap_lines=True)
        st.json(ex.response if ex.response is not None else {"error": ex.error}, expanded=2)


def envelope(ex: Exchange) -> None:
    """Every error from the API has the same shape: code, message, how_to_fix, details, correlation_id."""
    if ex.status is None:
        st.error(f"Couldn't reach the API: {ex.error}. Start it with `make run`.")
        return
    err = ex.response.get("error") if isinstance(ex.response, dict) else None
    if not err:
        st.error(f"HTTP {ex.status}")
        return
    st.error(f"**{err['code']}** (HTTP {ex.status}): {err['message']}")
    for hint in err.get("how_to_fix") or []:
        st.markdown(f"- {hint}")
    if err.get("details"):
        st.json(err["details"], expanded=1)


def status_badge(status: str) -> None:
    st.badge(status, color=STATUS_COLORS.get(status, "blue"))


def trace_steps(trace: dict) -> None:
    st.markdown(
        f"`{trace['method']} {trace['path']}` · status **{trace['status']}** · "
        f"{trace['duration_ms']} ms · started {trace['started_at']}"
    )
    st.dataframe(
        [
            {"#": s["seq"], "step": s["name"], "status": s["status"], "ms": s["duration_ms"]}
            for s in trace["steps"]
        ],
        hide_index=True,
    )
    for s in trace["steps"]:
        icon = "✅" if s["status"] == "ok" else "⚠️"
        with st.expander(f"{icon} {s['seq']}. {s['name']} ({s['duration_ms']} ms)"):
            left, right = st.columns(2)
            left.caption("input")
            left.json(s["input"], expanded=True)
            right.caption("output")
            right.json(s["output"], expanded=True)
