"""
Memory Service — two-level memory:
  Level 1: in-memory session state (via st.session_state passed in as dict)
  Level 2: persistent Neo4j interaction records

Entity Working Set (TTL-based Graph Memory):
  Each entity in the working set carries a `ttl` (turns remaining) and a `source`
  tag ("tool_result" | "ner" | "memory").  On every agent turn, entities
  decay by 1; expired entries are removed automatically.
  The working set is persisted to Neo4j so it survives page refreshes.

Conversation History:
  Every message (user + assistant) is written to Neo4j as a ConversationMessage
  node keyed by (sessionId, msgIndex).  init_session() restores the full history
  on page reload so conversations are never lost.

UI-click entity (Tier 1):
  NOT stored in the working set and has NO TTL.
  It is active exactly while the user has it selected; cleared on demand.
"""
import json
from datetime import datetime
from services.neo4j_service import run_cypher


MAX_RECENT_QUERIES = 5

# TTL defaults (turns)
TTL_NER = 3          # NER-extracted entities from current query
TTL_TOOL_RESULT = 5  # entities surfaced by tool/graph results (explicitly retrieved)


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ── Neo4j conversation persistence ───────────────────────────────────────────

def _persist_message(session_id: str, index: int, role: str, content: str, meta: dict = None):
    """Write (or overwrite) one conversation message node in Neo4j."""
    meta_str = json.dumps(meta, default=str) if meta else ""
    run_cypher(
        "MERGE (m:ConversationMessage {sessionId: $sid, msgIndex: $idx}) "
        "SET m.role = $role, m.content = $content, m.metaJson = $meta, m.timestamp = $now",
        {
            "sid":   session_id,
            "idx":   index,
            "role":  role,
            "content": content,
            "meta":  meta_str,
            "now":   _now_str(),
        },
    )


def _load_conversation_from_neo4j(session_id: str) -> list:
    """Return full conversation history for a session, ordered by message index."""
    rows = run_cypher(
        "MATCH (m:ConversationMessage {sessionId: $sid}) "
        "RETURN m.msgIndex AS idx, m.role AS role, "
        "m.content AS content, m.metaJson AS meta "
        "ORDER BY m.msgIndex ASC",
        {"sid": session_id},
    )
    messages = []
    for row in rows:
        entry = {"role": row["role"], "content": row["content"]}
        meta_str = row.get("meta", "")
        if meta_str:
            try:
                entry["_meta"] = json.loads(meta_str)
            except Exception:
                pass
        messages.append(entry)
    return messages


def _delete_conversation_from_neo4j(session_id: str):
    run_cypher(
        "MATCH (m:ConversationMessage {sessionId: $sid}) DELETE m",
        {"sid": session_id},
    )


# ── Neo4j working-set persistence ────────────────────────────────────────────

def _persist_working_set(session_id: str, working_set: list):
    """Serialise the entity working set onto the UserSession node."""
    run_cypher(
        "MERGE (us:UserSession {sessionId: $sid}) "
        "SET us.workingSetJson = $json",
        {"sid": session_id, "json": json.dumps(working_set, default=str)},
    )


def _load_working_set_from_neo4j(session_id: str) -> list:
    """Deserialise the entity working set from the UserSession node."""
    rows = run_cypher(
        "MATCH (us:UserSession {sessionId: $sid}) RETURN us.workingSetJson AS json",
        {"sid": session_id},
    )
    if rows and rows[0].get("json"):
        try:
            return json.loads(rows[0]["json"])
        except Exception:
            pass
    return []


# ── Session state initialization ─────────────────────────────────────────────

def init_session(session_state: dict, session_id: str):
    """
    Initialize in-memory session state, restoring persisted data from Neo4j
    when the session already exists (e.g. after a page refresh).
    """
    # Ensure UserSession node exists
    run_cypher(
        "MERGE (us:UserSession {sessionId: $sid}) "
        "ON CREATE SET us.startTime = $now",
        {"sid": session_id, "now": _now_str()},
    )

    # Always-present non-persistent keys
    for key, default in [
        ("session_id",           session_id),
        ("clicked_entity",       None),
        ("recent_queries",       []),
        ("last_results",         []),
        ("pending_confirmation", None),
    ]:
        if key not in session_state:
            session_state[key] = default

    # Restore conversation history from Neo4j if Streamlit lost it (page refresh)
    if "conversation_history" not in session_state:
        session_state["conversation_history"] = _load_conversation_from_neo4j(session_id)

    # Restore entity working set from Neo4j if Streamlit lost it
    if "entity_working_set" not in session_state:
        session_state["entity_working_set"] = _load_working_set_from_neo4j(session_id)

    # pending_confirmation is intentionally NOT restored on refresh — it is
    # transient UI state that only applies to the active session interaction.


# ── Clicked entity (Tier 1) — NO TTL, on/off only ────────────────────────────

def record_clicked_entity(session_state: dict, entity_type: str, entity_id: str, properties: dict = None):
    """Update clicked_entity in session state and persist to Neo4j."""
    session_state["clicked_entity"] = {
        "type":       entity_type,
        "identifier": entity_id,
        "properties": properties or {},
    }
    record_interaction(
        session_id=session_state.get("session_id", "unknown"),
        event_type="CLICK_ENTITY",
        entity_type=entity_type,
        entity_id=entity_id,
        content=f"Clicked {entity_type}: {entity_id}",
    )


def get_clicked_entity(session_state: dict) -> dict | None:
    return session_state.get("clicked_entity")


# ── Query history ─────────────────────────────────────────────────────────────

def record_query(session_state: dict, query: str, results: list):
    """Store a Cypher query in recent_queries (rolling window)."""
    recent = session_state.get("recent_queries", [])
    recent.insert(0, query)
    session_state["recent_queries"] = recent[:MAX_RECENT_QUERIES]
    session_state["last_results"] = results


# ── Conversation history ──────────────────────────────────────────────────────

def append_message(session_state: dict, role: str, content: str, metadata: dict = None):
    """
    Append a message to conversation_history and persist it to Neo4j.
    `metadata` (assistant only) stores context/tool info for UI display:
      rewritten_question, ner_context, tool_calls_made, reasoning, working_set, primitive_key
    """
    entry = {"role": role, "content": content}
    if metadata:
        entry["_meta"] = metadata
    history = session_state.setdefault("conversation_history", [])
    history.append(entry)
    # Persist to Neo4j
    session_id = session_state.get("session_id", "default")
    _persist_message(session_id, len(history) - 1, role, content, metadata)


def get_conversation_history(session_state: dict, last_n: int = 20) -> list:
    """Return last N messages as plain {role, content} dicts for OpenAI API calls."""
    return [
        {"role": m["role"], "content": m["content"]}
        for m in session_state.get("conversation_history", [])[-last_n:]
    ]


def get_full_conversation_history(session_state: dict) -> list:
    """Return all messages including _meta for UI rendering."""
    return list(session_state.get("conversation_history", []))


def clear_conversation(session_state: dict):
    session_state["conversation_history"] = []
    session_id = session_state.get("session_id", "default")
    _delete_conversation_from_neo4j(session_id)


# ── Persistent Neo4j interaction recording ───────────────────────────────────

def record_interaction(
    session_id: str,
    event_type: str,
    entity_type: str = "",
    entity_id: str = "",
    content: str = "",
    resolved_intent: str = "",
):
    """Write an InteractionEvent node linked to the UserSession."""
    now = _now_str()
    event_id = f"IE-{session_id}-{now.replace(' ', 'T').replace(':', '')}-{event_type}"
    run_cypher(
        "MERGE (us:UserSession {sessionId: $sid}) "
        "CREATE (ie:InteractionEvent { "
        "  eventId: $event_id, eventType: $etype, entityType: $entity_type, "
        "  entityId: $entity_id, content: $content, "
        "  timestamp: $now, resolvedIntent: $intent "
        "}) "
        "CREATE (us)-[:PERFORMED]->(ie)",
        {
            "sid":         session_id,
            "event_id":    event_id,
            "etype":       event_type,
            "entity_type": entity_type,
            "entity_id":   entity_id,
            "content":     content[:500],
            "now":         now,
            "intent":      resolved_intent,
        },
    )


# ── Pending confirmation persistence ─────────────────────────────────────────

def _persist_pending(session_id: str, pending: dict | None):
    """Store or clear the pending confirmation JSON on the UserSession node."""
    run_cypher(
        "MERGE (us:UserSession {sessionId: $sid}) "
        "SET us.pendingConfirmationJson = $json",
        {"sid": session_id, "json": json.dumps(pending, default=str) if pending else ""},
    )


def _load_pending_from_neo4j(session_id: str) -> dict | None:
    rows = run_cypher(
        "MATCH (us:UserSession {sessionId: $sid}) RETURN us.pendingConfirmationJson AS json",
        {"sid": session_id},
    )
    if rows and rows[0].get("json"):
        try:
            return json.loads(rows[0]["json"])
        except Exception:
            pass
    return None


def set_pending_confirmation(session_state: dict, pending: dict | None):
    """Set (or clear) pending confirmation in session state only (not persisted — transient)."""
    session_state["pending_confirmation"] = pending


# ── Entity Working Set (TTL-based Graph Memory) ───────────────────────────────

def get_entity_working_set(session_state: dict) -> list[dict]:
    """Return the current entity working set."""
    return list(session_state.get("entity_working_set", []))


def decay_entity_working_set(session_state: dict) -> list[dict]:
    """
    Decrement TTL on every entity by 1 each agent turn.
    Remove entries whose TTL has reached 0.
    Persists the surviving set to Neo4j.
    Returns the surviving active set.
    """
    active = []
    for e in session_state.get("entity_working_set", []):
        entry = dict(e)
        entry["ttl"] = entry.get("ttl", 1) - 1
        if entry["ttl"] > 0:
            active.append(entry)
    session_state["entity_working_set"] = active
    _persist_working_set(session_state.get("session_id", "default"), active)
    return active


def upsert_entities(session_state: dict, new_entities: list[dict]):
    """
    Add or refresh entities in the working set.
    If an entity with the same (label, id) already exists its TTL is bumped up
    to the new value (never reduced).
    Persists the updated set to Neo4j.

    Each entity dict should have:
        { "label": str, "id": str, "description": str,
          "source": "tool_result"|"ner"|"memory", "ttl": int }
    """
    wset: dict[tuple, dict] = {
        (e["label"], e["id"]): dict(e)
        for e in session_state.get("entity_working_set", [])
    }
    for new_e in new_entities:
        key = (new_e["label"], new_e["id"])
        if key in wset:
            wset[key]["ttl"] = max(wset[key]["ttl"], new_e["ttl"])
            wset[key]["source"] = new_e["source"]
            if new_e.get("description"):
                wset[key]["description"] = new_e["description"]
        else:
            wset[key] = dict(new_e)
    session_state["entity_working_set"] = list(wset.values())
    _persist_working_set(session_state.get("session_id", "default"),
                         session_state["entity_working_set"])


def clear_entity_working_set(session_state: dict):
    session_state["entity_working_set"] = []
    _persist_working_set(session_state.get("session_id", "default"), [])


def get_session_context(session_id: str, last_n: int = 10) -> list:
    """Return the last N interactions for a session (for agent context)."""
    return run_cypher(
        "MATCH (us:UserSession {sessionId: $sid})-[:PERFORMED]->(ie:InteractionEvent) "
        "RETURN ie.eventType AS event_type, ie.entityType AS entity_type, "
        "ie.entityId AS entity_id, ie.content AS content, "
        "ie.timestamp AS timestamp, ie.resolvedIntent AS resolved_intent "
        "ORDER BY ie.timestamp DESC LIMIT $n",
        {"sid": session_id, "n": last_n},
    )
