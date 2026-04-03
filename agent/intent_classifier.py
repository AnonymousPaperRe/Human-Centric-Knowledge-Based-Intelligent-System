"""
Intent Classifier — classifies user questions into one of three categories:
  - specific: data retrieval with identifiers or quantitative terms
  - high_level: analytical/evaluative questions requiring aggregation
  - context_aware: ambiguous questions that depend on the clicked entity
"""
import json
from openai import OpenAI
from config import OPENAI_API_KEY, OPENAI_MODEL


_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=OPENAI_API_KEY)
    return _client


CLASSIFICATION_SYSTEM_PROMPT = """You are an intent classifier for an automotive manufacturing knowledge base system.
Classify user questions into exactly one of three categories:

SPECIFIC — user wants specific data retrieval:
  Signals: entity identifiers present, quantitative terms (how many, count, list, which, find, show, what are), explicit date/time references, filter conditions.
  Examples: "What parts are affected by CS-2025-001?", "How many vehicles completed today?", "List all APPROVED ChangeSets"

HIGH_LEVEL — user wants analytics/evaluation/summary:
  Signals: evaluative verbs (evaluate, analyze, assess, summarize), broad scope (all, overall, today's, this week), no single entity focus, trend/status questions.
  Examples: "Evaluate today's production", "What is the overall impact of recent changes?", "How is Shop 321 performing?"

CONTEXT_AWARE — question is ambiguous and relies on the currently selected entity:
  Signals: pronouns (it, this, that, its), "show me more", "what's its status?", question makes no sense without a clicked entity context.
  Examples: "What's its status?", "Show me related specs", "What depends on it?"

Respond ONLY with a JSON object (no markdown):
{
  "category": "specific" | "high_level" | "context_aware",
  "entity_refs": ["list", "of", "entity", "identifiers", "or", "types", "mentioned"],
  "needs_context": true | false,
  "reasoning": "one sentence explanation"
}"""


def classify(question: str, clicked_entity: dict | None = None) -> dict:
    """
    Classify a user question.
    Returns: {"category": str, "entity_refs": list, "needs_context": bool, "reasoning": str}
    """
    context_str = "None"
    if clicked_entity:
        context_str = (
            f"{clicked_entity.get('type', '')} — {clicked_entity.get('identifier', '')} "
            f"({json.dumps(clicked_entity.get('properties', {}))[:200]})"
        )

    user_msg = f"Clicked entity context: {context_str}\n\nUser question: {question}"

    try:
        resp = _get_client().chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": CLASSIFICATION_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0,
            max_tokens=256,
        )
        raw = resp.choices[0].message.content.strip()
        result = json.loads(raw)
        # Normalize category
        cat = result.get("category", "specific").lower()
        if cat not in ("specific", "high_level", "context_aware"):
            cat = "specific"
        result["category"] = cat
        return result
    except Exception as exc:
        # Fallback: treat as specific
        return {
            "category": "specific",
            "entity_refs": [],
            "needs_context": False,
            "reasoning": f"Classification failed ({exc}), defaulting to specific.",
        }
