"""
Query Planner — clarity assessment + deterministic primitive dispatch.

Clarity levels:
  "clear"    — Tier 1 (UI click) or Tier 2 (NER) resolved the query subject
  "inferred" — subject filled only from Tier 3 memory; agent should ask to confirm
  "unclear"  — no subject resolved; agent should ask user to specify

Dispatch:
  resolve_entity_pairs() merges all tiers into (label, id) pairs.
  plan_query() tries every pair combination against GRAPH_PRIMITIVES keys
  built as "{labelA}_to_{labelB}" — no separate mapping dict needed.
"""
from agent.graph_primitives import lookup_primitive
from services import neo4j_service


def assess_clarity(
    clicked_entity: dict | None,
    ner_pairs: list[tuple],
    working_set: list[dict],
) -> str:
    """
    Return clarity level based on which context tier resolved the subject.

    - "clear"    → Tier 1 click OR Tier 2 NER extracted entities
    - "inferred" → only Tier 3 working-set memory has context
    - "unclear"  → all tiers empty
    """
    if clicked_entity:
        return "clear"
    if ner_pairs:
        return "clear"
    if working_set:
        return "inferred"
    return "unclear"


def resolve_entity_pairs(
    clicked_entity: dict | None,
    ner_pairs: list[tuple],
    working_set: list[dict],
) -> list[tuple[str, str]]:
    """
    Merge Tier 1 + Tier 2 + Tier 3 into an ordered, deduplicated list of
    (label, id) pairs. Priority: clicked_entity → NER → working set.

    Example:
      clicked = {type: "Vehicle", identifier: "V-001"}
      ner_pairs = [("PartBatch", "B-42", "identifier")]
      → [("Vehicle", "V-001"), ("PartBatch", "B-42")]
    """
    seen: set[tuple] = set()
    result: list[tuple[str, str]] = []

    def _add(label: str, eid: str):
        k = (label, eid)
        if k not in seen and label and eid:
            seen.add(k)
            result.append(k)

    if clicked_entity:
        _add(clicked_entity.get("type", ""), clicked_entity.get("identifier", ""))
    for label, val, _ in ner_pairs:
        _add(label, val)
    for e in working_set:
        _add(e.get("label", ""), e.get("id", ""))

    return result


def plan_query(entity_pairs: list[tuple[str, str]]) -> dict:
    """
    Try every ordered pair from entity_pairs against GRAPH_PRIMITIVES.
    Key is built as f"{labelA}_to_{labelB}" — lookup_primitive also tries
    the reversed order automatically.

    Returns the first matching primitive result, or a non-deterministic sentinel.

    Examples:
      [("Vehicle","V-001"), ("WorkStep","WS-42")]
        → tries "Vehicle_to_WorkStep" → match → execute and return

      [("Vehicle","V-001"), ("PartBatch","B-17")]
        → tries "Vehicle_to_PartBatch" → match → execute and return

      Future: [("Operation","OP-1"), ("ProductionOrder","PO-5")]
        → tries "Operation_to_ProductionOrder" → match when added to GRAPH_PRIMITIVES
    """
    for i, (label_a, id_a) in enumerate(entity_pairs):
        for j, (label_b, id_b) in enumerate(entity_pairs):
            if i >= j:
                continue  # avoid duplicates and self-pairs
            primitive = lookup_primitive(label_a, id_a, label_b, id_b)
            if primitive:
                result = neo4j_service.safe_run(primitive["cypher"], primitive["params"])
                return {
                    "deterministic": True,
                    "primitive_key": primitive["key"],
                    "cypher": primitive["cypher"],
                    "params": primitive["params"],
                    "data": result.get("data", []),
                    "ok": result.get("ok", False),
                    "error": result.get("error"),
                }

    return {
        "deterministic": False,
        "primitive_key": None,
        "cypher": None,
        "data": [],
        "ok": False,
        "error": None,
    }
