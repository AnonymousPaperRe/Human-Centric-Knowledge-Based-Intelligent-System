"""
AUTOAM — Automotive Knowledge-Based System
Main Streamlit entry point.

Interaction Layer — Agent Chat, Query Templates, Cypher Query
"""
import uuid
import streamlit as st

# ── Page config (must be first Streamlit call) ────────────────────────────────
st.set_page_config(
    page_title="Automotive KBS",
    page_icon="A",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── DB connection ─────────────────────────────────────────────────────────────
from services import neo4j_service, memory_service

@st.cache_resource
def init_db():
    try:
        neo4j_service.connect()
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

_db_status = init_db()

# ── Session initialization — stable across page refreshes ─────────────────────
# Session ID is persisted in the URL query param "sid" so that a browser
# refresh restores the same Neo4j-backed conversation and working set.
if "session_id" not in st.session_state:
    _sid = st.query_params.get("sid")
    if not _sid:
        _sid = str(uuid.uuid4())
    st.session_state["session_id"] = _sid

# Keep URL in sync (no-op if already set to same value)
if st.query_params.get("sid") != st.session_state["session_id"]:
    st.query_params["sid"] = st.session_state["session_id"]

memory_service.init_session(st.session_state, st.session_state["session_id"])

# ── Import UI pages ───────────────────────────────────────────────────────────
from ui import (
    agent_page,
    template_page,
    cypher_page,
)

# ── Sidebar navigation ─────────────────────────────────────────────────────────
with st.sidebar:
    st.title("Automotive KBS")
    st.markdown("---")

    st.markdown("**INTERACTION LAYER**")
    st.caption("Agent Chat · Query Templates · Cypher")

    active_page = st.radio(
        "nav",
        options=[
            "Agent Chat",
            "Query Templates",
            "Cypher Query",
        ],
        label_visibility="collapsed",
        key="nav_main",
    )

    st.markdown("---")

    # Entity context badge
    clicked = st.session_state.get("clicked_entity")
    if clicked:
        st.markdown("**Active entity context:**")
        st.info(f"**{clicked['type']}**\n\n`{clicked['identifier']}`")
    else:
        st.caption("No entity selected")

    st.markdown("---")
    if not _db_status.get("ok"):
        st.error(f"Neo4j: {_db_status.get('error', 'connection failed')}")
    else:
        st.caption("Neo4j: connected")
    st.caption(f"Session: `{st.session_state['session_id'][:8]}...`")


# ── Route to page ──────────────────────────────────────────────────────────────
if active_page == "Agent Chat":
    agent_page.render()
elif active_page == "Query Templates":
    template_page.render()
elif active_page == "Cypher Query":
    cypher_page.render()
else:
    agent_page.render()
