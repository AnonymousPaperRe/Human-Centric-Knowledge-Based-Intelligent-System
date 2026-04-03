"""
Context Manager — manages the clicked entity and session state helpers for the agent.
"""
import streamlit as st


def set_clicked_entity(entity_type: str, entity_id: str, properties: dict = None):
    """Store clicked entity in Streamlit session state."""
    st.session_state["clicked_entity"] = {
        "type": entity_type,
        "identifier": entity_id,
        "properties": properties or {},
    }


def get_clicked_entity() -> dict | None:
    """Retrieve the currently clicked entity from session state."""
    return st.session_state.get("clicked_entity")


def clear_clicked_entity():
    st.session_state["clicked_entity"] = None


def resolve_context_question(question: str, clicked_entity: dict) -> str:
    """
    Rewrite an ambiguous context-aware question to an explicit specific question
    by substituting the clicked entity reference.
    """
    if not clicked_entity:
        return question

    entity_type = clicked_entity.get("type", "entity")
    entity_id = clicked_entity.get("identifier", "unknown")

    # Replace common pronouns with explicit entity reference
    replacements = [
        ("its ", f"{entity_type} {entity_id}'s "),
        (" it ", f" {entity_type} {entity_id} "),
        (" it?", f" {entity_type} {entity_id}?"),
        ("this ", f"{entity_type} {entity_id} "),
        ("that ", f"{entity_type} {entity_id} "),
        ("show me more", f"show details of {entity_type} {entity_id}"),
    ]
    resolved = question
    for pattern, replacement in replacements:
        resolved = resolved.replace(pattern, replacement)

    # If no replacement happened, just prepend the entity context
    if resolved == question:
        resolved = f"For {entity_type} with identifier '{entity_id}': {question}"

    return resolved


def get_session_summary() -> dict:
    """Return a summary of current session state for the agent system prompt."""
    clicked = get_clicked_entity()
    return {
        "clicked_entity": clicked,
        "recent_queries": st.session_state.get("recent_queries", [])[:3],
        "conversation_turns": len(st.session_state.get("conversation_history", [])) // 2,
    }
