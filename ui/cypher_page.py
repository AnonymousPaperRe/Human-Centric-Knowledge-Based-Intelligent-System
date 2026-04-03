"""
Cypher Query Interface
- Persistent query history with full results (session-level)
- User-managed saved queries (stored in Neo4j, persist across sessions)
"""
import streamlit as st
from datetime import datetime
from services import neo4j_service, memory_service

MAX_HISTORY = 20
DEFAULT_QUERY = "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count ORDER BY count DESC LIMIT 20"


# ── Saved-query Neo4j helpers ─────────────────────────────────────────────────

def _list_saved() -> list:
    r = neo4j_service.safe_run(
        "MATCH (sq:SavedQuery) RETURN sq.name AS name, sq.cypher AS cypher "
        "ORDER BY sq.name"
    )
    return r["data"] if r["ok"] else []


def _save_query(name: str, cypher: str):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    neo4j_service.safe_run(
        "MERGE (sq:SavedQuery {name: $name}) SET sq.cypher = $cypher, sq.createdAt = $now",
        {"name": name, "cypher": cypher, "now": now},
    )


def _delete_saved(name: str):
    neo4j_service.safe_run(
        "MATCH (sq:SavedQuery {name: $name}) DELETE sq",
        {"name": name},
    )


# ── Page ──────────────────────────────────────────────────────────────────────

def render():
    st.header("Cypher Query Interface")

    # Ensure history list exists in session
    if "query_history" not in st.session_state:
        st.session_state["query_history"] = []

    # ── Query editor ──────────────────────────────────────────────────────────
    prefill = st.session_state.pop("_prefill_query", DEFAULT_QUERY)

    query = st.text_area(
        "Cypher Query",
        value=prefill,
        height=160,
        placeholder="MATCH (n:PartSpec) RETURN n.identifier, n.status LIMIT 10",
    )

    col1, col2 = st.columns([1, 8])
    with col1:
        run_clicked = st.button("▶ Run", type="primary")
    with col2:
        clear_clicked = st.button("Clear")

    if clear_clicked:
        st.session_state["_prefill_query"] = DEFAULT_QUERY
        st.rerun()

    # ── Execute ───────────────────────────────────────────────────────────────
    if run_clicked and query.strip():
        with st.spinner("Executing…"):
            result = neo4j_service.safe_run(query.strip())

        if result["ok"]:
            data = result["data"]

            # Push to session history (newest first, capped)
            st.session_state["query_history"].insert(0, {
                "query": query.strip(),
                "data": data,
                "row_count": len(data),
                "timestamp": datetime.now().strftime("%H:%M:%S"),
            })
            st.session_state["query_history"] = st.session_state["query_history"][:MAX_HISTORY]

            # Keep recent_queries string list for agent context
            memory_service.record_query(st.session_state, query.strip(), data)
            memory_service.record_interaction(
                session_id=st.session_state.get("session_id", "default"),
                event_type="EXECUTE_CYPHER",
                content=query.strip()[:500],
            )

            st.success(f"Returned {len(data)} record(s).")
            if data:
                st.dataframe(data, width="stretch")
            else:
                st.info("Query returned no results.")
        else:
            st.error(f"Query error: {result['error']}")

    st.markdown("---")

    # ── Bottom tabs ───────────────────────────────────────────────────────────
    tab_hist, tab_saved = st.tabs(["History", "Saved Queries"])

    with tab_hist:
        _render_history()

    with tab_saved:
        _render_saved_queries(query)


# ── History tab ───────────────────────────────────────────────────────────────

def _render_history():
    history = st.session_state.get("query_history", [])
    if not history:
        st.info("No queries run yet this session.")
        return

    # ── Toolbar: count + clear-all ────────────────────────────────────────────
    col_info, col_clear = st.columns([5, 1])
    with col_info:
        st.caption(f"{len(history)} entr{'y' if len(history) == 1 else 'ies'} this session")
    with col_clear:
        if st.button("🗑 Clear all", key="hist_clear_all"):
            st.session_state["query_history"] = []
            st.rerun()

    # ── Individual entries ────────────────────────────────────────────────────
    for i, entry in enumerate(history):
        preview = entry["query"][:70] + ("…" if len(entry["query"]) > 70 else "")
        label = f"`{entry['timestamp']}`  ·  {entry['row_count']} row(s)  ·  {preview}"
        with st.expander(label, expanded=(i == 0)):
            st.code(entry["query"], language="cypher")
            col_load, col_del, col_spacer = st.columns([1, 1, 6])
            with col_load:
                if st.button("Load", key=f"hist_load_{i}"):
                    st.session_state["_prefill_query"] = entry["query"]
                    st.rerun()
            with col_del:
                if st.button("Delete", key=f"hist_del_{i}"):
                    st.session_state["query_history"].pop(i)
                    st.rerun()
            if entry["data"]:
                st.dataframe(entry["data"], width="stretch")
            else:
                st.caption("No rows returned.")


# ── Saved queries tab ─────────────────────────────────────────────────────────

def _render_saved_queries(current_query: str):
    # Add / overwrite a saved query
    with st.form("add_saved_form", clear_on_submit=True):
        st.markdown("**Save a query for reuse:**")
        col_name, col_cypher = st.columns([2, 5])
        with col_name:
            new_name = st.text_input("Name", placeholder="e.g. All active PartSpecs")
        with col_cypher:
            new_cypher = st.text_area(
                "Cypher",
                value=current_query,
                height=90,
                help="Pre-filled with the current editor content.",
            )
        if st.form_submit_button("Save"):
            if new_name.strip() and new_cypher.strip():
                _save_query(new_name.strip(), new_cypher.strip())
                st.success(f"Saved: '{new_name.strip()}'")
                st.rerun()
            else:
                st.warning("Both Name and Cypher are required.")

    st.markdown("---")

    # List saved queries
    saved = _list_saved()
    if not saved:
        st.info("No saved queries yet. Save one using the form above.")
        return

    for row in saved:
        col_text, col_load, col_del = st.columns([6, 1, 1])
        with col_text:
            with st.expander(f"**{row['name']}**"):
                st.code(row["cypher"], language="cypher")
        with col_load:
            st.write("")  # vertical align
            if st.button("Load", key=f"sv_load_{row['name']}"):
                st.session_state["_prefill_query"] = row["cypher"]
                st.rerun()
        with col_del:
            st.write("")
            if st.button("Delete", key=f"sv_del_{row['name']}"):
                _delete_saved(row["name"])
                st.rerun()
