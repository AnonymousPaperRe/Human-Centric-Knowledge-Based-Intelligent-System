"""
Agent Orchestrator — Human-in-the-Loop pipeline:
  Phase 1: NER → rewrite → clarity check → HITL Gate 1 (implicit context)
  Phase 2: Entity count routing
    Scenario A (1 entity):  single-node lookup
    Scenario B (2 entities): _check_decomposability → INDEPENDENT (2×single) | RELATIONAL (primitive → tool loop)
    Scenario D (3+ entities): _decompose_to_primitives → HITL Gate 2 → Python set ops
"""
import json
import logging
import re
import textwrap
import threading
import uuid
from openai import OpenAI
from config import OPENAI_API_KEY, OPENAI_MODEL
from agent import intent_classifier, context_manager, ner
from agent.tools import TOOL_DEFINITIONS, dispatch
from agent.query_planner import resolve_entity_pairs, plan_query
from agent.graph_primitives import GRAPH_PRIMITIVES, lookup_primitive
from services import memory_service, neo4j_service, kg_schema_service


_client = None
logger = logging.getLogger(__name__)

# ── Per-request token accumulator ─────────────────────────────────────────────
_tlocal = threading.local()

def _reset_tokens() -> None:
    _tlocal.prompt = 0
    _tlocal.completion = 0

def _acc_tokens(usage) -> None:
    """Add usage from an OpenAI response object (safe if usage is None)."""
    if usage is None:
        return
    if not hasattr(_tlocal, "prompt"):
        _reset_tokens()
    _tlocal.prompt     += getattr(usage, "prompt_tokens",     0) or 0
    _tlocal.completion += getattr(usage, "completion_tokens", 0) or 0

def _token_usage() -> dict:
    return {
        "prompt_tokens":     getattr(_tlocal, "prompt",     0),
        "completion_tokens": getattr(_tlocal, "completion", 0),
    }


def _request_log_meta(session_state: dict | None = None) -> dict:
    session_state = session_state or {}
    return {
        "request_id": session_state.get("_active_request_id", ""),
        "session_id": session_state.get("session_id", "default"),
    }

# ── Deterministic time-property map ───────────────────────────────────────────
# Maps a KG entity label to the canonical (node_label, [property_names]) pair
# to use for temporal WHERE clauses.  The "node_label" may differ from the
# query entity when dates live on a related Version node.
#
# Rules from the domain model:
#   • Version / Specification / State subclasses → validFrom, validTo, createTime
#     (accessed on the node directly — these classes ARE the version/spec nodes)
#   • ProductionPlan / ProductionOrder          → plannedStartTime, plannedEndTime
#     (on ProductionPlanVersion / ProductionOrderVersion via CURRENT_VERSION)
#   • ProductionProcess / OperationalTask       → startTime, endTime  (on the node directly)
#   • Base plan/process-plan entities (Operation, WorkStep, Part, Equipment …)
#     → validFrom, validTo, createTime  on their *Version* companion node
_ENTITY_TIME_PROPS: dict[str, tuple[str, list[str]]] = {
    # Execution nodes — dates directly on the node
    "ProductionProcess": ("ProductionProcess", ["startTime", "endTime"]),
    "OperationalTask":   ("OperationalTask",   ["startTime", "endTime"]),

    # Plan nodes — dates on their Version node via CURRENT_VERSION
    "ProductionPlan":  ("ProductionPlanVersion",  ["plannedStartTime", "plannedEndTime"]),
    "ProductionOrder": ("ProductionOrderVersion",  ["plannedStartTime", "plannedEndTime"]),

    # Process-plan base entities — dates on their Version node via CURRENT_VERSION
    "Operation": ("OperationVersion", ["validFrom", "validTo", "createTime"]),
    "WorkStep":  ("WorkStepVersion",  ["validFrom", "validTo", "createTime"]),
    "Part":      ("PartSpec",         ["validFrom", "validTo", "createTime"]),

    # Equipment subtypes — dates on their Spec node via CURRENT_SPECIFICATION
    "Equipment":                    ("EquipmentSpec",                    ["validFrom", "validTo", "createTime"]),
    "RoboticEquipment":             ("RoboticEquipmentSpec",             ["validFrom", "validTo", "createTime"]),
    "ProcessEquipment":             ("ProcessEquipmentSpec",             ["validFrom", "validTo", "createTime"]),
    "DiagnosticEquipment":          ("DiagnosticEquipmentSpec",          ["validFrom", "validTo", "createTime"]),
    "MaterialHandlingEquipment":    ("MaterialHandlingEquipmentSpec",    ["validFrom", "validTo", "createTime"]),
    "ManualTool":                   ("ManualToolSpec",                   ["validFrom", "validTo", "createTime"]),
    "PrecisionTool":                ("PrecisionToolSpec",                ["validFrom", "validTo", "createTime"]),

    # Version / Specification / State nodes themselves — dates on the node directly
    "OperationVersion":     ("OperationVersion",     ["validFrom", "validTo", "createTime"]),
    "WorkStepVersion":      ("WorkStepVersion",      ["validFrom", "validTo", "createTime"]),
    "ProductionPlanVersion":("ProductionPlanVersion",["plannedStartTime", "plannedEndTime"]),
    "ProductionOrderVersion":("ProductionOrderVersion",["plannedStartTime", "plannedEndTime"]),
    "PartSpec":             ("PartSpec",             ["validFrom", "validTo", "createTime"]),
    "OperationSpec":        ("OperationSpec",        ["validFrom", "validTo", "createTime"]),
    "WorkStepSpec":         ("WorkStepSpec",         ["validFrom", "validTo", "createTime"]),
    "EquipmentSpec":        ("EquipmentSpec",        ["validFrom", "validTo", "createTime"]),
}

# Default property to use when the user says "in <year>" with no explicit qualifier
# (validFrom = when the spec/version became active is the most natural match)
_TIME_PROP_DEFAULT_INDEX: dict[str, int] = {
    "validFrom":          0,
    "plannedStartTime":   0,
    "startTime":          0,
}


def _resolve_time_property(label: str, llm_property: str) -> tuple[str, str]:
    """
    Return (canonical_node_label, canonical_property) for a time condition.
    If the label is in _ENTITY_TIME_PROPS:
      - Always use the canonical node label from the map.
      - Keep llm_property if it is in the valid list; else default to the first entry.
    Falls back to (label, llm_property) when the label is unknown.
    """
    if label in _ENTITY_TIME_PROPS:
        node_label, valid_props = _ENTITY_TIME_PROPS[label]
        prop = llm_property if llm_property in valid_props else valid_props[0]
        return node_label, prop
    return label, llm_property

SCHEMA_SUMMARY = """
The Neo4j knowledge graph contains these main node types:
- ProductDesign: VehicleFamily, VehicleVariant, Vehicle
- PlantOrganization: ManufacturingPlant, AssemblyShop, ProductionShop, ProductionPlan, ProductionOrder
- ProcessPlan: Part, Equipment subtypes (ManualTool, PrecisionTool, RoboticEquipment,
  ProcessEquipment, DiagnosticEquipment, MaterialHandlingEquipment), Operation, WorkStep
- ProductionProcess: ProductionProcess, OperationalTask, Personnel,
  PartInstance (MaterialLot, SerializedPart), EquipmentInstance subtypes
- Logistics: Supplier, StorageLocation
- DigitalThread: Specification children (PartSpec, EquipmentSpec, WorkStepSpec, OperationSpec,
  ProductionPlanSpec, ProductionOrderSpec, ProductDocumentSpec, ManualToolSpec, PrecisionToolSpec,
  DiagnosticEquipmentSpec, ProcessEquipmentSpec, RoboticEquipmentSpec, MaterialHandlingEquipmentSpec),
  State children (ProductionProcessState, PersonnelState, EquipmentState, InventoryRecordState)
- Events: ChangeSet, ChangeAction, EffectivityScope
"""

_REWRITER_SYSTEM_PROMPT = textwrap.dedent("""
    You are a QUERY REWRITER for an Automotive Manufacturing Knowledge Graph.

    YOUR TASK: Rewrite the user's ambiguous input into a self-contained question AND
    extract any temporal or attribute conditions present in the query.

    YOU ARE NOT answering the question. YOU ARE NOT looking up any data.

    Task 1 — Rewrite:
    Produce a single, standalone, unambiguous question using these rules (strict priority):
    1. NER entities in the current query (highest priority): Any entity the user explicitly
       named or identified in their input takes precedence over all context sources.
       Preserve these exactly as written — do NOT override them with UI or session context.
    2. Pronouns (this / that / it / those / here): Resolve using context in this order:
       a. Tier 1 — UI Selection: Replace the pronoun with the selected entity type and ID.
          CRITICAL: Use the exact `ID` value from [Tier 1], not the name or other property.
       b. Tier 3 — Session Memory: If no UI selection, fill from active_entities.
    3. KG Label Substitution: Replace colloquial names with canonical KG labels from [Detected KG Labels].
       e.g. "order" → "ProductionOrder", "car" → "Vehicle", "factory" → "ManufacturingPlant"

    Task 2 — Temporal conditions:
    If the question contains a date/time constraint, identify WHICH entity label it applies to
    and extract ONE condition entry per bound — each with a single operator and value.
    Use the [Time Properties] table to find the correct property name — do NOT invent names.
    Use the base entity label (e.g. "Operation", not "OperationVersion") — resolved from the table.
    Normalize all date/time values to 'YYYY-MM-DD HH:MM:SS'.
    Do NOT include entity identifiers (e.g. "Part P001", "Order PO1015") — handled by NER.
    Set time_conditions to [] if no time constraint.

    Mapping rules (produce as many entries as needed):
      "in 2025"          → two entries: {op:">=", val:"2025-01-01 00:00:00"} AND
                                         {op:"<", val:"2026-01-01 00:00:00"}
      "after 2025"       → one entry:  {op:">=", val:"2026-01-01 00:00:00"}
      "before 2025"      → one entry:  {op:"<",  val:"2025-01-01 00:00:00"}
      "in March 2025"    → two entries: {op:">=", val:"2025-03-01 00:00:00"} AND
                                         {op:"<", val:"2025-04-01 00:00:00"}
      "from 2024 to 2025"→ two entries: {op:">=", val:"2024-01-01 00:00:00"} AND
                                         {op:"<", val:"2026-01-01 00:00:00"}
      "valid in 2025"    → two entries on DIFFERENT properties (overlap check):
                            {property:"validFrom", op:"<", val:"2026-01-01 00:00:00"} AND
                            {property:"validTo",   op:">=", val:"2025-01-01 00:00:00"}
      "on 2025-10-02"    → two entries: {op:">=", val:"2025-10-02 00:00:00"} AND
                                         {op:"<",  val:"2025-10-03 00:00:00"}

    Task 3 — Property conditions:
    Extract only non-instance attribute filters (NOT entity identifiers with specific IDs).
    CRITICAL: Use ONLY property names that appear in the [KG Schema] section of the user message.
    Map each condition to the correct KG node label and its exact Neo4j property name from the schema.

    CRITICAL EXCLUSION — Do NOT extract a condition when the question is ASKING FOR the value of a
    property, not filtering by it. The test: is there an explicit target value in the question?
      "What is the status of X?"          → asking for status — NO condition (no target value given)
      "Show me the details of X"          → asking for details — NO condition
      "What properties does X have?"      → asking for properties — NO condition
      "X with status ACTIVE"              → filtering by status — EXTRACT condition
      "find Personnel where role is Operator" → filtering — EXTRACT condition
    If the question only asks ABOUT a property without stating a filter value, set property_conditions to [].

    Examples to INCLUDE (filtering — explicit value constraint in the question text):
      "active vehicles"           → {"label":"Vehicle","property":"status","operator":"=","value":"ACTIVE"}
      "active operations"         → use the schema to find the correct property (e.g. "current_status"), then:
                                    {"label":"Operation","property":"current_status","operator":"=","value":"ACTIVE"}
      "approved parts"            → {"label":"Part","property":"status","operator":"=","value":"APPROVED"}
      "type contains Robotic"     → {"label":"Equipment","property":"name","operator":"CONTAINS","value":"Robotic"}
      "quantity > 5"              → {"label":"Part","property":"quantity","operator":">","value":"5"}
      "status is COMPLETED"       → use exact property name from schema for that label
      "current / active / latest" → map to the status/state property shown in [KG Schema] for that label
      "role is Operator"          → {"label":"Personnel","property":"role","operator":"=","value":"Operator"}
    Examples to SKIP:
      "Part P001", "ProductionOrder PO1015", "Vehicle LSVWC..." (instance IDs, handled by NER)
      "What is the status of PL011015?"   (asking FOR status, no filter value — set property_conditions to [])
      "Tell me about this plan"           (no filter at all — set property_conditions to [])
    Set property_conditions to [] if none found.

    OUTPUT: JSON only — no explanation, no markdown.
    {
      "rewritten": "<rewritten question ending with ?>",
      "time_conditions": [
        {"label": "<NodeLabel>", "property": "<propName>",
         "operator": ">="|"<="|">"|"<", "value": "YYYY-MM-DD HH:MM:SS"}
      ],
      "property_conditions": [
        {"label": "<NodeLabel>", "property": "<propName>",
         "operator": "="|">"|"<"|">="|"<="|"CONTAINS"|"STARTS WITH", "value": "<val>"}
      ]
    }
""").strip()


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=OPENAI_API_KEY)
    return _client


def _clip_for_log(value: str, limit: int = 300) -> str:
    value = value or ""
    return value if len(value) <= limit else value[:limit] + "..."


# ── Question rewriter ──────────────────────────────────────────────────────────

def _build_rewriter_user_message(
    ner_rewritten: str,
    clicked_entity: dict | None,
    ner_pairs: list[tuple],
    working_set: list[dict],
    node_labels: list[tuple] | None = None,
    schema_hint: str = "",
) -> str:
    parts = []
    if clicked_entity:
        ctype = clicked_entity.get("type", "")
        cid   = clicked_entity.get("identifier", "")
        props = clicked_entity.get("properties", {})
        desc  = ", ".join(f"{k}:{v}" for k, v in list(props.items())[:3]) if props else ctype
        parts.append(
            f"[Tier 1 — UI Selection]\n"
            f"  Type: {ctype}\n"
            f"  ID: {cid}\n"
            f"  Description: {desc}"
        )
    else:
        parts.append("[Tier 1 — UI Selection]\n  None")

    if ner_pairs:
        lines = "\n".join(
            f"  - {label}: {val} ({attr})"
            for label, val, attr in ner_pairs
            if label != "Unknown"
        )
        parts.append(f"[Tier 2 — NER Entities in Query]\n{lines}" if lines
                     else "[Tier 2 — NER Entities in Query]\n  None detected")
    else:
        parts.append("[Tier 2 — NER Entities in Query]\n  None detected")

    mem_entities = [e for e in working_set if e.get("source") != "ui_click"]
    if mem_entities:
        ae_str = ", ".join(f"{e['label']}:{e['id']} (ttl={e['ttl']})" for e in mem_entities)
        parts.append(
            f"[Tier 3 — Session Memory]\n"
            f"  Active entities: {ae_str}"
        )
    else:
        parts.append("[Tier 3 — Session Memory]\n  Empty")

    if node_labels:
        label_str = ", ".join(f"{lbl} ({score:.0%})" for lbl, score in node_labels)
        parts.append(
            f"[Detected KG Labels — use these exact CamelCase names in the rewrite]\n"
            f"  {label_str}"
        )

    # Always include the deterministic time-property table (compact, no LLM guessing)
    time_table_lines = []
    for base_lbl, (node_lbl, props) in _ENTITY_TIME_PROPS.items():
        # Only show base entities (not the Version/Spec duplicates) to keep it concise
        if not any(base_lbl.endswith(sfx) for sfx in ("Version", "Spec", "State")):
            via = f" (via CURRENT_VERSION/CURRENT_SPECIFICATION → {node_lbl})" if node_lbl != base_lbl else ""
            time_table_lines.append(f"  {base_lbl}{via}: {', '.join(props)}")
    parts.append(
        "[Time Properties — use ONLY these for Task 2 temporal conditions]\n"
        + "\n".join(time_table_lines)
    )

    if schema_hint:
        parts.append(
            f"[KG Schema — use ONLY these property names for Task 3 attribute conditions]\n"
            f"{schema_hint}"
        )

    parts.append(f"[User's Raw Input (NER pre-processed)]\n\"{ner_rewritten}\"")
    return "\n\n".join(parts)


def _rewrite_question(
    ner_rewritten: str,
    clicked_entity: dict | None,
    ner_pairs: list[tuple],
    working_set: list[dict],
    node_labels: list[tuple] | None = None,
) -> dict:
    """
    Rewrite the question for clarity and extract temporal/property conditions.

    Returns:
        {
            "rewritten":           str,          # rewritten question
            "time_conditions":     list[dict],   # temporal filters (may be [])
            "property_conditions": list[dict],   # attribute filters (may be [])
        }
    """
    _fallback = {"rewritten": ner_rewritten, "time_conditions": [], "property_conditions": []}

    has_context = bool(clicked_entity or ner_pairs or working_set)
    ambiguous_tokens = {"it", "its", "this", "that", "here", "they", "them",
                        "what", "which", "how"}
    words = set(re.findall(r'\b\w+\b', ner_rewritten.lower()))
    looks_ambiguous = bool(words & ambiguous_tokens)

    # Also rewrite when colloquial entity type names need canonical substitution
    has_label_synonyms = bool(node_labels)

    if not (has_context or has_label_synonyms) or not (looks_ambiguous or has_label_synonyms):
        return _fallback

    # Fetch the live schema (1-hop BFS) for all detected labels so the LLM picks
    # property names that actually exist in Neo4j instead of guessing them.
    schema_hint = ""
    if node_labels:
        from services import kg_schema_service
        label_list = [lbl for lbl, _ in node_labels]
        try:
            schema_hint = kg_schema_service.get_subschema_by_hops(label_list, hops=1)
        except Exception:
            pass

    user_msg = _build_rewriter_user_message(
        ner_rewritten, clicked_entity, ner_pairs, working_set, node_labels,
        schema_hint=schema_hint,
    )
    try:
        resp = _get_client().chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": _REWRITER_SYSTEM_PROMPT},
                {"role": "user",   "content": user_msg},
            ],
            temperature=0.2,
            max_tokens=450,
            response_format={"type": "json_object"},
        )
        _acc_tokens(resp.usage)
        result = json.loads(resp.choices[0].message.content)
        rewritten = (result.get("rewritten") or "").strip()
        # Accept any non-empty rewrite that looks like a sentence (question OR
        # imperative statement).  The old endswith("?") check rejected valid
        # rewrites for commands like "Tell me about X and Y".
        if rewritten and len(rewritten) > 10:
            # Post-process time_conditions: resolve node label + property deterministically.
            # Handles two formats from the LLM:
            #   NEW (preferred): {label, property, operator, value}  — one bound per entry
            #   OLD (fallback):  {label, property, type, start, end} — expand to two bounds
            raw_time = result.get("time_conditions") or []
            time_conditions = []
            for tc in raw_time:
                lbl  = tc.get("label", "")
                prop = tc.get("property", "")
                resolved_lbl, resolved_prop = _resolve_time_property(lbl, prop)
                if tc.get("operator") and tc.get("value"):
                    # New single-bound format
                    time_conditions.append({
                        "label":    resolved_lbl,
                        "property": resolved_prop,
                        "operator": tc["operator"],
                        "value":    tc["value"],
                    })
                elif tc.get("start") or tc.get("end"):
                    # Old start/end format — expand to two bounds (<= / <)
                    if tc.get("start"):
                        time_conditions.append({
                            "label": resolved_lbl, "property": resolved_prop,
                            "operator": ">=", "value": tc["start"],
                        })
                    if tc.get("end"):
                        time_conditions.append({
                            "label": resolved_lbl, "property": resolved_prop,
                            "operator": "<", "value": tc["end"],
                        })
            return {
                "rewritten":           rewritten,
                "time_conditions":     time_conditions,
                "property_conditions": result.get("property_conditions") or [],
            }
        logger.warning(
            "rewrite_question returned unusable output",
            extra={
                "stage": "rewrite_question",
                "question": _clip_for_log(ner_rewritten),
                "output": _clip_for_log(resp.choices[0].message.content),
            },
        )
    except Exception:
        logger.exception(
            "rewrite_question failed",
            extra={
                "stage": "rewrite_question",
                "question": _clip_for_log(ner_rewritten),
            },
        )
    return _fallback


# ── Result narrator ────────────────────────────────────────────────────────────

def _summarize_graph_result(question: str, plan_result: dict) -> str:
    data_str = json.dumps(plan_result["data"][:20], default=str)
    try:
        resp = _get_client().chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a KBS assistant summarizing graph query results. "
                        "Answer the question concisely using only the provided data. "
                        "Cite specific identifiers and names from the results."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Question: {question}\n\nGraph data:\n{data_str}",
                },
            ],
            temperature=0.3,
            max_tokens=400,
        )
        _acc_tokens(resp.usage)
        return resp.choices[0].message.content.strip()
    except Exception:
        logger.exception(
            "summarize_graph_result failed; using raw fallback",
            extra={
                "stage": "summarize_graph_result",
                "question": _clip_for_log(question),
                "result_count": len(plan_result.get("data", [])),
            },
        )
        return f"Query returned {len(plan_result['data'])} results:\n```json\n{data_str}\n```"


# ── Result entity extractor ───────────────────────────────────────────────────

def _extract_result_entities(tool_name: str, tool_args: dict, result_str: str) -> list[dict]:
    entities: list[dict] = []
    seen: set[tuple] = set()

    try:
        result = json.loads(result_str)
    except Exception:
        return entities

    data = result.get("data", [])
    if not isinstance(data, list):
        return entities

    for row in data:
        if not isinstance(row, dict):
            continue
        for key, val in row.items():
            if isinstance(val, dict) and "identifier" in val:
                eid = str(val["identifier"])
                if eid and (key, eid) not in seen:
                    seen.add((key, eid))
                    desc = str(val.get("name", "") or val.get("identifier", ""))
                    entities.append({
                        "label":       key,
                        "id":          eid,
                        "description": desc,
                        "source":      "tool_result",
                        "ttl":         memory_service.TTL_TOOL_RESULT,
                    })

    if tool_name == "get_entity_details":
        etype = tool_args.get("entity_type", "")
        eid   = tool_args.get("identifier", "")
        if etype and eid and (etype, eid) not in seen:
            entities.append({
                "label":       etype,
                "id":          eid,
                "description": f"{etype}:{eid}",
                "source":      "tool_result",
                "ttl":         memory_service.TTL_TOOL_RESULT,
            })

    return entities


# ── Result dict helper ────────────────────────────────────────────────────────

def _build_result(
    answer: str,
    intent: str,
    rewritten_question: str,
    tool_calls: list,
    reasoning: str,
    ner_result: dict,
    working_set: list,
) -> dict:
    return {
        "answer":             answer,
        "intent":             intent,
        "rewritten_question": rewritten_question,
        "tool_calls_made":    tool_calls,
        "reasoning":          reasoning,
        "ner_context":        ner_result,
        "working_set":        working_set,
        "_token_usage":       _token_usage(),
    }


# ── Scenario A: single-node lookup ────────────────────────────────────────────

def _execute_single_node_query(
    label: str,
    identifier: str,
    question: str,
    session_state: dict | None = None,
) -> tuple[str, list[dict], list[dict]]:
    """Returns (answer, tool_calls, result_entities)."""
    _meta = _request_log_meta(session_state)
    logger.warning(
        f"execute_single_node_query invoked request_id={_meta['request_id']} session_id={_meta['session_id']}",
        extra={
            "stage": "single_node_query",
            "label": label,
            "identifier": identifier,
            "question": _clip_for_log(question),
        },
    )
    args = {"entity_type": label, "identifier": identifier}
    result_str = dispatch("get_entity_details", args)
    try:
        result_obj = json.loads(result_str)
    except Exception:
        result_obj = {"ok": False, "data": [], "error": "parse error"}

    answer = _summarize_graph_result(question, result_obj)
    tool_calls = [{"tool": "get_entity_details", "args": args, "result_summary": result_str[:300]}]
    result_entities = _extract_result_entities("get_entity_details", args, result_str)
    return answer, tool_calls, result_entities


# ── Scenario B helpers ────────────────────────────────────────────────────────

_ANALYTICAL_KW = [
    "how many", "count", "total", "number of",
    "sort", "order by", "top ", "latest", "earliest", "recent",
    "most", "least", "highest", "lowest", "average", "avg",
    "sum", "max", "min", "compare", "percent", "ratio",
]


def _is_analytical(question: str) -> bool:
    """Return True if the question requires aggregation / sorting / comparison."""
    q = question.lower()
    return any(re.search(r'\b' + re.escape(k.strip()) + r'\b', q) for k in _ANALYTICAL_KW)


def _check_decomposability(question: str, entity_pairs: list) -> dict:
    """
    Classify the question as RELATIONAL or INDEPENDENT, and extract any
    date/time constraint present in the question.

    Returns:
        {
            "decomposability": "RELATIONAL" | "INDEPENDENT",
            "time_filter": {
                "type":  "point" | "duration",
                "start": "YYYY-MM-DD HH:MM:SS",
                "end":   "YYYY-MM-DD HH:MM:SS"
            } | null
        }

    time_filter rules:
      - "point"    → single day/time  → end = start + 1 day (midnight-to-midnight)
      - "duration" → month/year/range → end = first moment after the period
      - All values in 'YYYY-MM-DD HH:MM:SS' string format (no date() conversion).
    """
    entities_desc = "; ".join(f"{label}:{eid}" for label, eid in entity_pairs)
    entity_schema = _build_entity_schema(entity_pairs)
    system_prompt = textwrap.dedent(f"""
        You are a query classifier for an automotive manufacturing knowledge graph.

        Task 1 — Decomposability:
        Classify whether the question asks about a RELATIONAL link between entities
        or asks to display each entity INDEPENDENTLY.
        RELATIONAL examples: "which parts are used in operation X?",
          "find supplier for part Z", "which operation did personnel P do on date D?"
        INDEPENDENT examples: "show part P-001 and operation OP-001",
          "display details of vehicle V and order PO"

        Task 2 — Time filter:
        If the question contains a date/time constraint, normalize it to
        'YYYY-MM-DD HH:MM:SS' boundaries:
          - Single day  (e.g. "on 2015-10-01")  → type=point,
              start="2015-10-01 00:00:00", end="2015-10-02 00:00:00"
          - Month       (e.g. "in October 2015") → type=duration,
              start="2015-10-01 00:00:00", end="2015-11-01 00:00:00"
          - Year        (e.g. "in 2015")         → type=duration,
              start="2015-01-01 00:00:00", end="2016-01-01 00:00:00"
          - Explicit range (e.g. "from 2015-10 to 2015-12") → type=duration,
              start="2015-10-01 00:00:00", end="2016-01-01 00:00:00"
        If no time constraint is present, set time_filter to null.

        KG schema relevant to these entities:
        {entity_schema}

        OUTPUT FORMAT (JSON only, no explanation):
        {{
          "decomposability": "RELATIONAL" or "INDEPENDENT",
          "time_filter": {{
            "type":  "point" or "duration",
            "start": "YYYY-MM-DD HH:MM:SS",
            "end":   "YYYY-MM-DD HH:MM:SS"
          }} or null
        }}
    """).strip()
    try:
        resp = _get_client().chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": f"Question: {question}\nEntities: {entities_desc}"},
            ],
            temperature=0,
            max_tokens=120,
            response_format={"type": "json_object"},
        )
        _acc_tokens(resp.usage)
        result = json.loads(resp.choices[0].message.content)
        decomp = "INDEPENDENT" if "INDEPENDENT" in str(result.get("decomposability", "")).upper() else "RELATIONAL"
        tf = result.get("time_filter")
        if isinstance(tf, dict) and tf.get("start") and tf.get("end"):
            return {"decomposability": decomp, "time_filter": tf, "fallback_reason": None}
        return {"decomposability": decomp, "time_filter": None, "fallback_reason": None}
    except Exception:
        logger.exception(
            "check_decomposability failed; defaulting to RELATIONAL",
            extra={
                "stage": "check_decomposability",
                "question": _clip_for_log(question),
                "entity_pairs": _clip_for_log(str(entity_pairs)),
            },
        )
    return {
        "decomposability": "RELATIONAL",
        "time_filter": None,
        "fallback_reason": "decomposability_error",
    }


def _normalize_time_filter(question: str) -> dict | None:
    """
    Lightweight LLM call to extract and normalize a time constraint from a question.
    Used when _check_decomposability is skipped (has_type_hint=True).
    Returns {"type", "start", "end"} or None.
    """
    try:
        resp = _get_client().chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": textwrap.dedent("""
                        Extract any date/time constraint from the question and normalize to
                        'YYYY-MM-DD HH:MM:SS' boundaries.
                        Rules:
                          - Single day  → type=point,    start="YYYY-MM-DD 00:00:00", end=next day
                          - Month       → type=duration, start=first of month,         end=first of next month
                          - Year        → type=duration, start="YYYY-01-01 00:00:00", end=next year
                          - Range       → type=duration, use explicit start/end
                        If no time constraint, output {"time_filter": null}.
                        OUTPUT JSON only:
                        {"time_filter": {"type": "point"|"duration", "start": "...", "end": "..."}}
                        or {"time_filter": null}
                    """).strip(),
                },
                {"role": "user", "content": question},
            ],
            temperature=0,
            max_tokens=80,
            response_format={"type": "json_object"},
        )
        _acc_tokens(resp.usage)
        result = json.loads(resp.choices[0].message.content)
        tf = result.get("time_filter")
        if isinstance(tf, dict) and tf.get("start") and tf.get("end"):
            return tf
        # No time filter extracted — this is normal for queries without dates.
        # Log at debug level only; a warning here creates false alarms.
        logger.debug(
            "normalize_time_filter: no time filter in question",
            extra={
                "stage": "normalize_time_filter",
                "question": _clip_for_log(question),
                "output": _clip_for_log(resp.choices[0].message.content),
            },
        )
    except Exception:
        logger.exception(
            "normalize_time_filter failed",
            extra={
                "stage": "normalize_time_filter",
                "question": _clip_for_log(question),
            },
        )
    return None


# ── Scenario D: deterministic primitive chain builder ─────────────────────────

def _try_primitive_chain(
    anchor_label: str,
    anchor_id: str,
    type_hint_labels: list[str],
) -> list[dict] | None:
    """
    Try to build a deterministic sub-problem chain from a real anchor entity
    through a list of type-hint labels, using only GRAPH_PRIMITIVES lookups.

    Tries all orderings of type_hint_labels (up to 6 labels = 720 perms, but
    in practice 2-3 labels → 2-6 tries). Returns an ordered sub_problems list
    if a complete chain is found (each step has a direct primitive to the next
    label), otherwise returns None (caller falls back to LLM decomposition).

    Example:
        anchor = Vehicle:LSVWC6185F2010008
        type_hints = [AssemblyShop, ManufacturingPlant]
        → tries Vehicle→AssemblyShop (✓ Vehicle_to_AssemblyShop)
              then AssemblyShop→ManufacturingPlant (✓ AssemblyShop_to_ManufacturingPlant)
        → returns [SP1: Vehicle→AssemblyShop, SP2: AssemblyShop→ManufacturingPlant]
    """
    from itertools import permutations as _perms

    for ordering in _perms(type_hint_labels):
        chain: list[dict] = []
        cur_label = anchor_label
        cur_id    = anchor_id
        valid     = True

        for tgt_label in ordering:
            p = lookup_primitive(cur_label, cur_id, tgt_label, "")
            # Accept only when the real ID is used as source ($a_id matches)
            if p and (not cur_id or p["params"].get("a_id") == cur_id):
                chain.append({
                    "id":          f"s{len(chain) + 1}",
                    "type":        "two_node",
                    "label_a":     cur_label,
                    "id_a":        cur_id,
                    "label_b":     tgt_label,
                    "id_b":        "",
                    "description": (
                        f"Find {tgt_label} for {cur_label}"
                        + (f" {cur_id}" if cur_id else "")
                    ).strip(),
                })
                cur_label = tgt_label
                cur_id    = ""
            else:
                valid = False
                break

        if valid and len(chain) == len(type_hint_labels):
            return chain

    return None


# ── Scenario D: decompose 3+ entities into logic tree ─────────────────────────

def _decompose_to_primitives(question: str, entity_pairs: list) -> dict:
    """
    GPT-4o decomposes a 3+ entity question into 1-node/2-node sub-problems
    with a logic tree (AND / OR / NOT / LEAF). Returns a dict with keys:
    description, sub_problems, logic_tree, pivot_entity.
    """
    primitive_keys = list(GRAPH_PRIMITIVES.keys())[:60]
    entities_desc = json.dumps([{"label": l, "id": i} for l, i in entity_pairs])
    entity_schema = _build_entity_schema(entity_pairs)

    system_prompt = textwrap.dedent(f"""
        You are a query decomposer for an automotive manufacturing knowledge graph.

        TASK: Decompose the given question into fundamental 1-node or 2-node sub-problems
        combined by a logic tree (AND / OR / NOT).

        Available graph primitives (verified relationship paths):
        {", ".join(primitive_keys)}

        KG schema relevant to this query:
        {entity_schema}

        OUTPUT FORMAT (JSON only, no explanation):
        {{
          "description": "<human-readable plan, e.g.: Find vehicles with Part P-001 AND in ProductionOrder PO-001>",
          "sub_problems": [
            {{
              "id": "s1",
              "type": "two_node",
              "label_a": "<source label>",
              "id_a": "<source identifier or empty string>",
              "label_b": "<target label>",
              "id_b": "<target identifier or empty string>",
              "description": "<e.g.: Vehicles using Part P-001>"
            }}
          ],
          "logic_tree": {{
            "op": "AND",
            "operands": [{{"op": "LEAF", "step_id": "s1"}}, {{"op": "LEAF", "step_id": "s2"}}]
          }},
          "pivot_entity": "<label of entity type whose IDs are collected across sub-problems>"
        }}

        Rules:
        - op values: AND, OR, NOT, LEAF
        - LEAF node has key "step_id" pointing to a sub_problem id
        - NOT has a single "operands" list with one element
        - AND/OR have "operands" with 2+ elements
        - pivot_entity is the entity type whose result IDs are intersected/unioned/subtracted
        - For NOT: all pivot_entity IDs from graph minus the sub-problem result IDs
    """).strip()

    try:
        resp = _get_client().chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Question: {question}\nEntities: {entities_desc}"},
            ],
            temperature=0.1,
            max_tokens=700,
            response_format={"type": "json_object"},
        )
        _acc_tokens(resp.usage)
        result = json.loads(resp.choices[0].message.content)
        if "sub_problems" in result and "logic_tree" in result:
            return result
    except Exception:
        pass

    # Fallback: AND of all 2-node pair combinations
    sub_problems = []
    for i, (la, ia) in enumerate(entity_pairs):
        for j, (lb, ib) in enumerate(entity_pairs):
            if j > i:
                sub_problems.append({
                    "id": f"s{len(sub_problems) + 1}",
                    "type": "two_node",
                    "label_a": la, "id_a": ia,
                    "label_b": lb, "id_b": ib,
                    "description": f"{la}:{ia} ↔ {lb}:{ib}",
                })
    return {
        "description": (
            f"Analyze relationships among {', '.join(f'{l}:{i}' for l, i in entity_pairs)}"
        ),
        "sub_problems": sub_problems,
        "logic_tree": {
            "op": "AND",
            "operands": [{"op": "LEAF", "step_id": sp["id"]} for sp in sub_problems],
        },
        "pivot_entity": entity_pairs[0][0] if entity_pairs else "",
    }


# ── Status-condition heuristic (zero LLM, zero Neo4j) ────────────────────────

_STATUS_ADJECTIVES: dict[str, str] = {
    "active":      "ACTIVE",
    "current":     "ACTIVE",
    "inactive":    "INACTIVE",
    "completed":   "COMPLETED",
    "done":        "COMPLETED",
    "finished":    "COMPLETED",
    "approved":    "APPROVED",
    "rejected":    "REJECTED",
    "pending":     "PENDING",
    "running":     "RUNNING",
    "stopped":     "STOPPED",
    "cancelled":   "CANCELLED",
    "canceled":    "CANCELLED",
}

# Priority-ordered candidate status property names (checked against live schema)
_STATUS_PROP_CANDIDATES = [
    "current_status", "status", "stateType", "state", "current_state",
]


def _infer_status_condition(question: str, label: str) -> dict | None:
    """
    Check if the question contains a known status adjective and the label's schema
    has a matching status property. Returns a condition dict or None.

    Zero LLM calls, zero Neo4j calls — dict lookup + schema string scan only.
    """
    q_lower = question.lower()
    matched_value: str | None = None
    for word, value in _STATUS_ADJECTIVES.items():
        if re.search(r"\b" + word + r"\b", q_lower):
            matched_value = value
            break
    if not matched_value:
        return None

    # Fetch schema string for this label (cached, 1-hop, no Neo4j call if warm)
    try:
        from services import kg_schema_service
        schema_str = kg_schema_service.get_subschema_by_hops([label], hops=1)
    except Exception:
        schema_str = ""

    for prop_name in _STATUS_PROP_CANDIDATES:
        if prop_name in schema_str:
            return {
                "label":    label,
                "property": prop_name,
                "operator": "=",
                "value":    matched_value,
            }
    return None


# ── plan_query + condition injection (entity_count=2, no LLM) ────────────────

def _plan_query_with_conditions(
    entity_pairs: list,
    time_conditions: list[dict],
    property_conditions: list[dict],
) -> dict | None:
    """
    Find the primitive for entity_pairs (pure dict lookup, zero Neo4j),
    inject confirmed conditions as a WHERE clause, then execute ONCE.

    Returns a plan_result-like dict, or None if:
    - no primitive exists for this pair, OR
    - a condition's label has no named alias in the MATCH (can't inject safely).
    """
    all_conds = list(time_conditions) + list(property_conditions)

    # Find primitive via pure dict lookup (no Neo4j call)
    primitive = None
    for i, (label_a, id_a) in enumerate(entity_pairs):
        for j, (label_b, id_b) in enumerate(entity_pairs):
            if i >= j:
                continue
            p = lookup_primitive(label_a, id_a, label_b, id_b)
            if p:
                primitive = p
                break
        if primitive:
            break

    if not primitive:
        return None  # no primitive — caller falls back to tool loop

    cypher = primitive["cypher"]
    params = primitive["params"]

    if not all_conds:
        # No conditions: execute primitive as-is (same as plan_query but one call)
        result = neo4j_service.safe_run(cypher, params)
        return {
            "deterministic":  True,
            "primitive_key":  primitive["key"],
            "cypher":         cypher,
            "params":         params,
            "data":           result.get("data", []),
            "ok":             result.get("ok", False),
            "error":          result.get("error"),
        }

    # Extract label→alias from MATCH: matches `(alias:Label` patterns
    label_aliases: dict[str, str] = {}
    for m in re.finditer(r"\((\w+):(\w+)", cypher):
        label_aliases[m.group(2)] = m.group(1)

    # Build WHERE predicates — only for conditions whose label has a named alias
    where_parts: list[str] = []
    for c in all_conds:
        lbl  = c.get("label", "")
        prop = c.get("property", "")
        op   = c.get("operator", "=")
        val  = c.get("value", "")
        if not prop or val == "":
            continue
        alias = label_aliases.get(lbl)
        if not alias:
            return None  # can't inject this condition — fall back to tool loop
        val_cypher = (
            str(val) if str(val).lstrip("-").replace(".", "", 1).isdigit()
            else f"'{val}'"
        )
        if op in ("CONTAINS", "STARTS WITH", "ENDS WITH"):
            where_parts.append(f"{alias}.`{prop}` {op} '{val}'")
        else:
            where_parts.append(f"{alias}.`{prop}` {op} {val_cypher}")

    if not where_parts:
        result = neo4j_service.safe_run(cypher, params)
        return {
            "deterministic": True, "primitive_key": primitive["key"],
            "cypher": cypher, "params": params,
            "data": result.get("data", []), "ok": result.get("ok", False),
            "error": result.get("error"),
        }

    where_clause   = " AND ".join(where_parts)
    modified_cypher = (
        cypher.replace(" RETURN ", f" WHERE {where_clause} RETURN ", 1)
        if " RETURN " in cypher
        else cypher.replace("\nRETURN", f"\nWHERE {where_clause}\nRETURN", 1)
    )

    result = neo4j_service.safe_run(modified_cypher, params)
    return {
        "deterministic": True,
        "primitive_key": primitive["key"],
        "cypher":        modified_cypher,
        "params":        params,
        "data":          result.get("data", []),
        "ok":            result.get("ok", False),
        "error":         result.get("error"),
    }


# ── Condition template execution (entity_count=0, single label, no LLM) ──────

def _execute_condition_query_direct(
    label: str,
    time_conditions: list[dict],
    property_conditions: list[dict],
    question: str,
    identifier: str | None = None,
) -> tuple[str, list[dict]]:
    """
    Build and run a deterministic Cypher query from confirmed conditions.
    No LLM call — the WHERE clause is assembled directly from condition dicts.

    Used when entity_count=0, single primary label, all conditions on same label.
    When *identifier* is given (entity_count=1), the MATCH clause pins to that
    specific node so the user-edited condition values are applied exactly.
    """
    where_parts: list[str] = []
    for c in time_conditions + property_conditions:
        prop = c.get("property", "")
        op   = c.get("operator", "=")
        val  = c.get("value", "")
        if not prop or val == "":
            continue
        # Numeric values don't need quotes; everything else does
        if str(val).lstrip("-").replace(".", "", 1).isdigit():
            val_cypher = str(val)
        else:
            val_cypher = f"'{val}'"
        if op in ("CONTAINS", "STARTS WITH", "ENDS WITH"):
            where_parts.append(f"n.`{prop}` {op} '{val}'")
        else:
            where_parts.append(f"n.`{prop}` {op} {val_cypher}")

    where_clause = " AND ".join(where_parts) if where_parts else "true"
    is_count = _is_analytical(question)

    if identifier:
        match_clause = f"MATCH (n:`{label}` {{identifier: '{identifier}'}})"
    else:
        match_clause = f"MATCH (n:`{label}`)"

    if is_count:
        cypher = f"{match_clause} WHERE {where_clause} RETURN count(n) AS total"
    else:
        cypher = f"{match_clause} WHERE {where_clause} RETURN n LIMIT 50"

    result = neo4j_service.safe_run(cypher)
    _ct_rows = result.get("data", [])
    _ct_previews = []
    for _r in _ct_rows[:10]:
        _props = _r.get("n", _r) if "n" in _r else _r
        if isinstance(_props, dict):
            _ident = _props.get("identifier") or _props.get("name") or next(iter(_props.values()), "")
            _ct_previews.append(str(_ident))
        else:
            _ct_previews.append(str(_props))
    _ct_summary = f"{len(_ct_rows)} rows" + (
        "\n" + ", ".join(_ct_previews) if _ct_previews else ""
    )
    tool_call = {
        "tool":           "condition_template",
        "args":           {"query": cypher},
        "result_summary": _ct_summary,
    }

    if is_count and result.get("ok"):
        data  = result.get("data", [])
        count = data[0].get("total", 0) if data else 0
        answer = (
            f"There {'is' if count == 1 else 'are'} **{count}** "
            f"{label}(s) matching the conditions."
        )
    elif result.get("ok"):
        answer = _summarize_graph_result(question, result)
    else:
        answer = f"Query failed: {result.get('error', 'unknown error')}"

    return answer, [tool_call]


# ── Condition helpers ─────────────────────────────────────────────────────────

def _build_condition_description(
    time_conditions: list[dict],
    property_conditions: list[dict],
) -> str:
    """Format extracted conditions as a readable bullet list for chat display."""
    lines = []
    for tc in time_conditions:
        lines.append(
            f"- **Time** `{tc.get('label','')}.{tc.get('property','')} "
            f"{tc.get('operator','')} '{tc.get('value','')}'`"
        )
    for pc in property_conditions:
        lines.append(
            f"- **Filter** `{pc.get('label','')}.{pc.get('property','')} "
            f"{pc.get('operator','')} '{pc.get('value','')}'`"
        )
    return "\n".join(lines) if lines else "(none)"


def _build_condition_hint(
    time_conditions: list[dict],
    property_conditions: list[dict],
) -> str:
    """
    Format confirmed conditions as a primitive_hint suffix for the tool loop.
    Each entry in time_conditions and property_conditions has the same shape:
      {label, property, operator, value}
    They are rendered as individual WHERE clause predicates.
    """
    all_conds = list(time_conditions) + list(property_conditions)
    if not all_conds:
        return ""
    lines = ["  Conditions (apply as WHERE clauses using the node alias from MATCH):"]
    for c in all_conds:
        lbl  = c.get("label", "")
        prop = c.get("property", "")
        op   = c.get("operator", "=")
        val  = c.get("value", "")
        # String operators don't need quotes around value; comparison operators do
        if op in ("CONTAINS", "STARTS WITH", "ENDS WITH"):
            lines.append(f"    {lbl}.{prop} {op} '{val}'")
        else:
            lines.append(f"    {lbl}.{prop} {op} '{val}'")
    return "\n".join(lines)


def _execute_with_conditions(
    pending: dict,
    time_conditions: list[dict],
    property_conditions: list[dict],
    session_state: dict,
) -> tuple[str, list[dict]]:
    """
    Resume a deferred query with user-confirmed conditions.
    Runs Scenario A/B/D routing from the stored entity_pairs + rewritten_question,
    injecting the confirmed conditions into the primitive hint and needs_llm logic.
    """
    rewritten_question = pending["rewritten_question"]
    entity_pairs       = pending["entity_pairs"]
    node_labels        = pending.get("node_labels", [])
    question           = pending["original_question"]
    session_id         = pending.get("session_id", "default")
    max_tool_rounds    = 6

    # Defensive dedupe: pending state can occasionally carry the same anchor
    # twice across reruns, which incorrectly pushes 1-entity confirmations into
    # the 2-entity INDEPENDENT branch and causes duplicate single-node lookups.
    _seen_pairs: set[tuple[str, str]] = set()
    _deduped_pairs: list[tuple[str, str]] = []
    for label, eid in entity_pairs:
        pair = (label, eid)
        if pair in _seen_pairs:
            continue
        _seen_pairs.add(pair)
        _deduped_pairs.append(pair)
    entity_pairs = _deduped_pairs

    clicked_entity = context_manager.get_clicked_entity()
    working_set    = memory_service.get_entity_working_set(session_state)

    condition_hint = _build_condition_hint(time_conditions, property_conditions)
    _any_cond      = bool(time_conditions or property_conditions)

    tool_calls:      list[dict] = []
    result_entities: list[dict] = []
    answer = ""

    entity_count = len(entity_pairs)
    _meta = _request_log_meta(session_state)
    logger.warning(
        f"_execute_with_conditions branch inputs request_id={_meta['request_id']} session_id={_meta['session_id']}",
        extra={
            "stage": "execute_with_conditions_inputs",
            "entity_pairs": _clip_for_log(str(entity_pairs)),
            "entity_count": entity_count,
            "time_conditions": _clip_for_log(json.dumps(time_conditions, default=str)),
            "property_conditions": _clip_for_log(json.dumps(property_conditions, default=str)),
            **_meta,
        },
    )

    if entity_count == 0:
        label_pairs     = [(lbl, "") for lbl, score in node_labels if score >= 0.5]
        primary_labels  = [lbl for lbl, score in node_labels if score >= 0.5]

        # Template path: single label + all conditions on that label → direct Cypher, no LLM
        _use_template = (
            len(primary_labels) == 1
            and (time_conditions or property_conditions)
            and all(
                not c.get("label") or c.get("label") == primary_labels[0]
                for c in time_conditions + property_conditions
            )
        )
        if _use_template:
            answer, tool_calls = _execute_condition_query_direct(
                primary_labels[0], time_conditions, property_conditions, rewritten_question
            )
        else:
            answer, tool_calls, result_entities, _, _ = _run_tool_loop(
                question, rewritten_question, clicked_entity, working_set, label_pairs,
                session_state, session_id, max_tool_rounds, primitive_hint=condition_hint,
            )

    elif entity_count == 1:
        label, eid = entity_pairs[0]
        if _any_cond:
            # When conditions target a DIFFERENT label from the anchor (cross-entity),
            # augment entity_pairs with condition labels and use _plan_query_with_conditions
            # so the WHERE clause lands on the correct node alias, not the anchor.
            # e.g. anchor=OperationalTask + condition.label=Personnel → need primitive
            #      OperationalTask→Personnel with WHERE p.role = 'operator', not n.role.
            _cond_labels = {
                c.get("label", "") for c in time_conditions + property_conditions
                if c.get("label") and c.get("label") != label
            }
            if _cond_labels:
                # Try each cross-entity condition label as a type hint
                _aug_pairs = list(entity_pairs)
                for _clbl in _cond_labels:
                    _aug_pairs.append((_clbl, ""))
                _cross_result = _plan_query_with_conditions(
                    _aug_pairs, time_conditions, property_conditions
                )
                if _cross_result and _cross_result.get("ok"):
                    answer = _summarize_graph_result(rewritten_question, _cross_result)
                    _rows = _cross_result.get("data", [])
                    _row_previews = [
                        " | ".join(
                            f"{k}: {v.get('identifier', v.get('name', str(v)))}"
                            if isinstance(v, dict) else f"{k}: {v}"
                            for k, v in _r.items()
                        )
                        for _r in _rows[:10]
                    ]
                    _summary = f"{len(_rows)} rows\n" + "\n".join(_row_previews)
                    tool_calls = [{
                        "tool": "plan_and_query_with_condition",
                        "args": {
                            "query":         _cross_result["cypher"],
                            "primitive_key": _cross_result["primitive_key"],
                        },
                        "result_summary": _summary,
                    }]
                    result_entities = []
                else:
                    # Cross-entity primitive not found → fall back to direct query
                    answer, tool_calls = _execute_condition_query_direct(
                        label, time_conditions, property_conditions,
                        rewritten_question, identifier=eid,
                    )
                    result_entities = []
            else:
                # Conditions are on the same label as the anchor — direct query is correct
                answer, tool_calls = _execute_condition_query_direct(
                    label, time_conditions, property_conditions,
                    rewritten_question, identifier=eid,
                )
                result_entities = []
        else:
            answer, tool_calls, result_entities = _execute_single_node_query(
                label, eid, rewritten_question, session_state
            )

    elif entity_count == 2:
        has_type_hint = any(eid == "" for _, eid in entity_pairs)
        if has_type_hint:
            decomp_intent = "RELATIONAL"
        else:
            decomp_result = _check_decomposability(rewritten_question, entity_pairs)
            decomp_intent = decomp_result["decomposability"]

        if decomp_intent == "INDEPENDENT":
            parts: list[str] = []
            for label, eid in entity_pairs:
                ans_part, tc_part, re_part = _execute_single_node_query(
                    label, eid, rewritten_question, session_state
                )
                parts.append(ans_part)
                tool_calls.extend(tc_part)
                result_entities.extend(re_part)
            answer = "\n\n---\n\n".join(parts)
        else:
            # Deterministic path: primitive + injected conditions (no LLM)
            # Only for non-analytical queries — analytics still need LLM for RETURN modification.
            if _any_cond and not _is_analytical(rewritten_question):
                cond_result = _plan_query_with_conditions(
                    entity_pairs, time_conditions, property_conditions
                )
                if cond_result and cond_result.get("ok"):
                    answer = _summarize_graph_result(rewritten_question, cond_result)
                    _rows = cond_result.get("data", [])
                    _row_previews = []
                    for _r in _rows[:10]:
                        _ids = [
                            f"{k}: {v.get('identifier', v.get('name', str(v)))}"
                            if isinstance(v, dict) else f"{k}: {v}"
                            for k, v in _r.items()
                        ]
                        _row_previews.append(" | ".join(_ids))
                    _summary = f"{len(_rows)} rows\n" + "\n".join(_row_previews)
                    tool_calls = [{
                        "tool": "plan_and_query_with_condition",
                        "args": {
                            "query":         cond_result["cypher"],
                            "primitive_key": cond_result["primitive_key"],
                        },
                        "result_summary": _summary,
                    }]
                    fake = json.dumps({"data": cond_result.get("data", [])})
                    result_entities = _extract_result_entities("plan_and_query", {}, fake)
                    return answer, tool_calls
                # Injection failed (no primitive or unresolvable alias) → fall through

            # Build a question string that embeds the exact user-confirmed condition
            # values so the LLM fallback can't revert to values from the original text.
            _q_with_exact_conds = rewritten_question
            _exact_cond_phrases = [
                f"{c.get('property', '')} {c.get('operator', '=')} '{c.get('value', '')}'"
                for c in property_conditions if c.get("property") and c.get("value") != ""
            ] + [
                f"{c.get('property', '')} {c.get('operator', '>=')} '{c.get('value', '')}'"
                for c in time_conditions if c.get("property") and c.get("value") != ""
            ]
            if _exact_cond_phrases:
                _q_with_exact_conds = (
                    rewritten_question.rstrip("?")
                    + " [confirmed filters: "
                    + "; ".join(_exact_cond_phrases)
                    + "]?"
                )

            plan_result = plan_query(entity_pairs)
            if plan_result["deterministic"] and plan_result["ok"]:
                needs_llm = _is_analytical(rewritten_question) or _any_cond
                if needs_llm:
                    hint = (
                        f"  Key:    {plan_result['primitive_key']}\n"
                        f"  Cypher: {plan_result['cypher']}\n"
                        + condition_hint
                    )
                    answer, tool_calls, result_entities, _, _ = _run_tool_loop(
                        question, _q_with_exact_conds, clicked_entity, working_set, entity_pairs,
                        session_state, session_id, max_tool_rounds, primitive_hint=hint,
                    )
                else:
                    answer = _summarize_graph_result(rewritten_question, plan_result)
                    tool_calls = [{
                        "tool": "plan_and_query",
                        "args": {"primitive_key": plan_result["primitive_key"]},
                        "result_summary": f"{len(plan_result['data'])} rows",
                    }]
                    fake = json.dumps({"data": plan_result.get("data", [])})
                    result_entities = _extract_result_entities("plan_and_query", {}, fake)
            else:
                hint = condition_hint
                if plan_result["deterministic"]:
                    hint = (
                        f"  Key:    {plan_result['primitive_key']}\n"
                        f"  Cypher: {plan_result['cypher']}\n"
                        + condition_hint
                    )
                answer, tool_calls, result_entities, _, _ = _run_tool_loop(
                    question, _q_with_exact_conds, clicked_entity, working_set, entity_pairs,
                    session_state, session_id, max_tool_rounds, primitive_hint=hint,
                )

    else:  # 3+ entities — just run tool loop with condition hint
        answer, tool_calls, result_entities, _, _ = _run_tool_loop(
            question, rewritten_question, clicked_entity, working_set, entity_pairs,
            session_state, session_id, max_tool_rounds, primitive_hint=condition_hint,
        )

    return answer, tool_calls


# ── Analytical primitive helper ───────────────────────────────────────────────

def _run_analytical_on_primitive(
    question: str,
    base_cypher: str,
    params: dict,
    tool_calls_out: list,
) -> str:
    """
    Ask the LLM to modify the RETURN clause of a known primitive Cypher to
    answer an analytical question (COUNT, ORDER BY, aggregation, etc.), then
    run the result.  Appends an execute_cypher entry to tool_calls_out.
    """
    client = _get_client()
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        temperature=0,
        messages=[
            {"role": "system", "content": (
                "You are a Cypher expert. Modify ONLY the RETURN clause of the given "
                "Cypher to answer the analytical question (COUNT, ORDER BY, aggregation, "
                "etc.). Keep the MATCH/WHERE clauses unchanged. "
                "Return ONLY the complete modified Cypher — no explanation, no markdown."
            )},
            {"role": "user", "content": f"Question: {question}\n\nBase Cypher:\n{base_cypher}"},
        ],
        max_tokens=400,
    )
    _acc_tokens(resp.usage)
    cypher = resp.choices[0].message.content.strip()
    cypher = re.sub(r"```\w*\n?", "", cypher).strip("`").strip()

    result = neo4j_service.safe_run(cypher, params)
    tool_calls_out.append({
        "tool": "execute_cypher",
        "args": {"query": cypher},
        "result_summary": f"ok={result.get('ok')} rows={len(result.get('data', []))}",
    })
    if result.get("ok") and result.get("data"):
        return _summarize_graph_result(question, result)
    return f"Analytical query returned no data: {result.get('error', '')}"


# ── Scenario D: execute confirmed decomposition ───────────────────────────────

def _execute_decomposition(pending: dict) -> tuple[str, list[dict]]:
    """
    Execute a confirmed complex_decomposition.

    Strategy:
      Step 1 (single-hop shortcut): When NER on the overall plan description detects
        exactly 2 distinct entity labels, try plan_query for a direct primitive.
        Used for simple queries like "find VehicleVariants using Part X".
        Skipped for chained queries (3+ labels) to avoid premature short-circuiting.

      Step 2 (sequential sub-problem execution):
        Execute sub-problems in declaration order.
        ID propagation: when a sub-problem's source ID is empty, fill it from
        the entity IDs produced by prior sub-problems for that label.
        Each sub-problem is executed via NER-on-description + plan_query.

      Step 3 (logic tree + summarize):
        AND / OR / NOT set operations on pivot entity IDs.
        Falls back to all raw sub-problem rows when no pivot IDs collected.
    """
    sub_problems  = pending.get("sub_problems", [])
    logic_tree    = pending.get("logic_tree", {})
    pivot_entity  = pending.get("pivot_entity", "")
    original_q    = pending.get("original_question", "")
    # Use the rewritten question (self-contained, pronouns resolved) for summarization.
    # Falls back to original_q when not available (older pending dicts).
    summary_q     = pending.get("rewritten_question") or original_q
    description   = pending.get("description", "")

    tool_calls: list[dict] = []
    produced_ids: dict[str, list[str]] = {}   # label → IDs produced across all steps

    # ── Split sub-problems into linked (participate in global pattern) and
    #    independent (looked up separately, combined narratively at the end).
    #    The "independent" flag is set by the user per-SP in the HITL UI.
    #    Default: one_node SPs are independent; two_node SPs are linked.
    linked_sps      = [sp for sp in sub_problems if not sp.get("independent", sp.get("type") == "one_node")]
    independent_sps = [sp for sp in sub_problems if     sp.get("independent", sp.get("type") == "one_node")]

    # ── Pattern detection (applies only to linked_sps) ────────────────────────
    # UI may supply an edited_pattern; otherwise auto-detect from linked sub-problems.
    _edited_pattern = pending.get("edited_pattern")

    def _is_chain(sps: list) -> bool:
        if len(sps) <= 1:
            return False
        return all(
            sps[i].get("label_b") == sps[i + 1].get("label_a")
            for i in range(len(sps) - 1)
        )

    def _detect_pattern(sps: list, tree: dict) -> str:
        if _edited_pattern:
            return _edited_pattern
        if _is_chain(sps):
            return "CHAIN"
        if sps and all(sp.get("type") == "one_node" for sp in sps):
            return "INDEPENDENT"
        tree_op = (tree or {}).get("op", "AND")
        # LLM sometimes says CHAIN when the sub-problems are not actually a chain
        # (e.g. two independent questions joined by "also").  Reject it here so
        # the INDEPENDENT path handles each sub-problem via plan_query separately.
        if tree_op == "CHAIN":
            return "INDEPENDENT"
        return tree_op

    exec_pattern = _detect_pattern(linked_sps, logic_tree)

    # When all SPs are independent (user checked every box, or only one_node SPs),
    # run them all through _append_independent_answers immediately.
    if not linked_sps:
        return _append_independent_answers("", independent_sps, summary_q, tool_calls)

    # Swap in linked_sps so all downstream logic operates on the linked set only.
    # Independent SPs are executed after the main pattern returns via
    # _append_independent_answers at every return site.
    sub_problems = linked_sps

    # ── INDEPENDENT: each sub-problem executed separately ────────────────────
    # one_node → _execute_single_node_query
    # two_node → plan_query (primitive lookup); fall back to tool loop if no primitive
    if exec_pattern == "INDEPENDENT":
        parts_ind: list[str] = []
        for sp in sub_problems:
            lbl_a = sp.get("label_a", "")
            id_a  = sp.get("id_a", "")
            lbl_b = sp.get("label_b", "")
            id_b  = sp.get("id_b", "")
            sp_desc = sp.get("description", summary_q)
            if sp.get("type") == "two_node" and lbl_b:
                # Ensure the entity with a real ID is the source ($a_id)
                src_lbl, src_id, tgt_lbl, tgt_id = lbl_a, id_a, lbl_b, id_b
                if not src_id and tgt_id:
                    src_lbl, src_id, tgt_lbl, tgt_id = lbl_b, id_b, lbl_a, id_a
                prim_r = plan_query([(src_lbl, src_id), (tgt_lbl, tgt_id)])
                if prim_r.get("deterministic") and prim_r.get("ok"):
                    sp_ans = _summarize_graph_result(sp_desc, prim_r)
                    _sp_rows = prim_r.get("data", [])
                    _sp_previews = []
                    for _r in _sp_rows[:10]:
                        _ids = [
                            f"{k}: {v.get('identifier', v.get('name', str(v)))}"
                            if isinstance(v, dict) else f"{k}: {v}"
                            for k, v in _r.items()
                        ]
                        _sp_previews.append(" | ".join(_ids))
                    _sp_summary = f"{len(_sp_rows)} rows" + (
                        "\n" + "\n".join(_sp_previews) if _sp_previews else ""
                    )
                    sp_tc  = [{"tool": "plan_and_query",
                               "args": {"query": prim_r["cypher"], "params": prim_r["params"]},
                               "result_summary": _sp_summary}]
                else:
                    sp_ans, sp_tc, _ = _run_tool_loop(
                        sp_desc, sp_desc, None, [], [(src_lbl, src_id), (tgt_lbl, tgt_id)],
                        {}, "default", 4,
                    )
                header = f"**{src_lbl}** `{src_id}` → **{tgt_lbl}**"
            else:
                sp_ans, sp_tc, _ = _execute_single_node_query(lbl_a, id_a, sp_desc)
                header = f"**{lbl_a}**" + (f" `{id_a}`" if id_a else "")
            parts_ind.append(f"{header}\n\n{sp_ans}")
            tool_calls.extend(sp_tc)
        main = "\n\n---\n\n".join(parts_ind) if parts_ind else "No results found."
        return _append_independent_answers(main, independent_sps, summary_q, tool_calls)

    # ── AND / OR: execute each sub-problem with stored IDs, then set-op ─────────
    # Both patterns need per-SP result sets to intersect (AND) or union (OR).
    # The common target entity type is the one shared across all sub-problems.
    # Sub-problems where the real ID is in label_b ("To ID") are swapped so the
    # real entity always becomes the source ($a_id).
    if exec_pattern in ("AND", "OR"):
        sp_rows_map:  dict[str, list]     = {}   # sp_id → raw rows
        sp_tgt_ids:   dict[str, set[str]] = {}   # sp_id → target entity ID set
        sp_tgt_label: dict[str, str]      = {}   # sp_id → target label name

        for sp in sub_problems:
            lbl_a = sp.get("label_a", "")
            id_a  = sp.get("id_a", "")
            lbl_b = sp.get("label_b", "")
            id_b  = sp.get("id_b", "")
            sp_id = sp.get("id", "")

            # Ensure the entity with a real ID is always the source
            src_lbl, src_id, tgt_lbl = lbl_a, id_a, lbl_b
            if not src_id and id_b:
                src_lbl, src_id, tgt_lbl = lbl_b, id_b, lbl_a

            prim_r = plan_query([(src_lbl, src_id), (tgt_lbl, "")])
            if not (prim_r.get("deterministic") and prim_r.get("ok")):
                continue

            rows = prim_r.get("data", [])
            # Collect target-entity identifiers
            tgt_ids: set[str] = set()
            for row in rows:
                val = row.get(tgt_lbl)
                if isinstance(val, dict):
                    eid = val.get("identifier")
                    if eid:
                        tgt_ids.add(str(eid))

            sp_rows_map[sp_id]  = rows
            sp_tgt_ids[sp_id]   = tgt_ids
            sp_tgt_label[sp_id] = tgt_lbl

            _prev = []
            for _r in rows[:10]:
                _ids = [
                    f"{k}: {v.get('identifier', v.get('name', str(v)))}"
                    if isinstance(v, dict) else f"{k}: {v}"
                    for k, v in _r.items()
                ]
                _prev.append(" | ".join(_ids))
            tool_calls.append({
                "tool": "plan_and_query",
                "args": {
                    "pairs":         str([(src_lbl, src_id), (tgt_lbl, "")]),
                    "primitive_key": prim_r["primitive_key"],
                },
                "result_summary": (
                    f"{len(rows)} rows\n" + "\n".join(_prev) if _prev
                    else f"{len(rows)} rows"
                ),
            })

        # Determine common target label (most frequent across sub-problems)
        _tgt_lbls = list(sp_tgt_label.values())
        common_tgt = max(set(_tgt_lbls), key=_tgt_lbls.count) if _tgt_lbls else ""

        # Collect ID sets only for sub-problems targeting the common label
        _id_sets = [
            sp_tgt_ids[sid]
            for sid in sp_tgt_ids
            if sp_tgt_label.get(sid) == common_tgt
        ]

        if exec_pattern == "AND":
            combined_ids = _id_sets[0].intersection(*_id_sets[1:]) if len(_id_sets) > 1 else (_id_sets[0] if _id_sets else set())
            op_name = "INTERSECTION"
        else:
            combined_ids = _id_sets[0].union(*_id_sets[1:]) if len(_id_sets) > 1 else (_id_sets[0] if _id_sets else set())
            op_name = "UNION"

        op_preview = ", ".join(sorted(combined_ids)[:15])
        tool_calls.append({
            "tool": f"set_{exec_pattern.lower()}",
            "args": {"operation": exec_pattern, "target_label": common_tgt},
            "result_summary": (
                f"{op_name}: {len(combined_ids)} {common_tgt}(s)\n{op_preview}"
                if combined_ids else f"{op_name}: 0 results"
            ),
        })

        if not combined_ids:
            return f"No {common_tgt or 'entity'} satisfies all the specified conditions.", tool_calls

        # Build rows for summarization: collect filtered rows from ALL sub-problems
        # (no break — OR needs rows from every SP; AND rows are the same entities
        # filtered to intersection IDs, so duplicates are harmless after dedup)
        seen_combined: set[str] = set()
        combined_rows: list[dict] = []
        for sid, rows in sp_rows_map.items():
            if sp_tgt_label.get(sid) == common_tgt:
                for row in rows:
                    val = row.get(common_tgt)
                    if isinstance(val, dict):
                        eid = str(val.get("identifier", ""))
                        if eid in combined_ids and eid not in seen_combined:
                            seen_combined.add(eid)
                            combined_rows.append(row)

        # Enrich the summary question with set-operation context.
        # Embed the combined IDs directly into the prompt so the LLM has the
        # answer explicitly — combined_rows may only carry rows from one source
        # sub-problem (due to dedup), which confuses the LLM about the other source.
        sp_descs = [sp.get("description", "") for sp in sub_problems if sp.get("description")]
        _ids_preview = ", ".join(sorted(combined_ids)[:50])
        set_context = (
            f"The {op_name} of {common_tgt}(s) satisfying all conditions "
            f"({'; '.join(sp_descs)}) contains exactly {len(combined_ids)} {common_tgt}(s):\n"
            f"{_ids_preview}\n\n"
            f"List these {common_tgt}(s) in a clear, organized format and confirm "
            f"that each one satisfies all stated conditions."
        )
        answer = _summarize_graph_result(
            set_context, {"ok": True, "data": combined_rows[:50]}
        )
        return _append_independent_answers(answer, independent_sps, summary_q, tool_calls)

    # ── Step 1: Direct primitive for non-chained plans ───────────────────────
    # A "chain" is when each sub-problem's target = the next sub-problem's source
    # (e.g. Vehicle→Plan then Plan→Plant). Chains need sequential ID propagation
    # in Step 2 and must NOT be short-circuited here.
    # Non-chains (parallel sub-problems sharing an artificial pivot, e.g. all
    # branching from Vehicle when the real path is Part→VehicleVariant) are
    # bypassed here by running NER on the overall plan description directly.
    if description and exec_pattern != "CHAIN":
        ner_plan = ner.extract_entities(description)

        # Real anchors: instances with known IDs
        # Deduplicate by (label, id) — NOT by label alone, so two entities of the
        # same type (e.g. two Parts in an AND/OR query) are both kept as anchors.
        anchors: list[tuple[str, str]] = []
        anchor_ids: set[tuple[str, str]] = set()
        anchor_seen: set[str] = set()  # label set used only for target exclusion below
        for lbl, val, _ in ner_plan.get("node_instance_pairs", []):
            key = (lbl, val)
            if lbl and val and key not in anchor_ids:
                anchors.append((lbl, val))
                anchor_ids.add(key)
                anchor_seen.add(lbl)

        # Type targets: label types without specific IDs
        targets: list[str] = []
        target_seen: set[str] = set(anchor_seen)
        for lbl, score in ner_plan.get("node_labels", []):
            if score >= 0.5 and lbl and lbl not in target_seen:
                targets.append(lbl); target_seen.add(lbl)

        # Try each (anchor, target_type) pair separately — do NOT merge all into one
        # plan_query call, which would greedily pick the first/shortest primitive and
        # skip intermediate entities (e.g. Vehicle→ManufacturingPlant skips Plan).
        step1_rows: list = []
        for a_lbl, a_id in anchors:
            for t_lbl in targets:
                p = lookup_primitive(a_lbl, a_id, t_lbl, "")
                if p and p["params"].get("a_id") == a_id:
                    res = neo4j_service.safe_run(p["cypher"], p["params"])
                    rows = res.get("data", []) if res.get("ok") else []
                    tool_calls.append({
                        "tool": "plan_and_query",
                        "args": {"pairs": str([(a_lbl, a_id), (t_lbl, "")]),
                                 "primitive_key": p["key"]},
                        "result_summary": f"{len(rows)} rows via {p['key']}",
                    })
                    step1_rows.extend(rows)
                    # Propagate produced IDs for potential downstream use (capped)
                    for row in rows:
                        if isinstance(row.get(t_lbl), dict):
                            nid = row[t_lbl].get("identifier")
                            if nid:
                                produced_ids.setdefault(t_lbl, [])
                                if nid not in produced_ids[t_lbl] and len(produced_ids[t_lbl]) < 20:
                                    produced_ids[t_lbl].append(nid)

        if tool_calls:   # at least one primitive was matched
            answer = _summarize_graph_result(summary_q, {"ok": True, "data": step1_rows})
            return _append_independent_answers(answer, independent_sps, summary_q, tool_calls)

    # ── Step 2: Sequential sub-problem execution with ID propagation ──────────
    # produced_ids (declared above) tracks entity IDs yielded by each step.
    # Later sub-problems with empty source IDs pull from here.
    sub_results:        dict[str, set]  = {}   # sp_id → pivot entity ID set
    sub_data:           dict[str, list] = {}   # sp_id → raw rows
    analytical_answers: list[str]      = []   # answers from analytical sub-problems
    relational_descs:   list[str]      = []   # descriptions of RELATIONAL sub-problems

    for sp in sub_problems:
        sp_id   = sp["id"]
        sp_type = sp.get("type", "two_node")

        if sp_type == "one_node":
            args = {"entity_type": sp["label_a"], "identifier": sp["id_a"]}
            result_str = dispatch("get_entity_details", args)
            tool_calls.append({
                "tool": "get_entity_details",
                "args": args,
                "result_summary": result_str[:300],
            })
            try:
                data = json.loads(result_str).get("data", [])
            except Exception:
                data = []
            sub_data[sp_id] = data
            sub_results[sp_id] = set()
            continue

        # ── two_node sub-problem ──────────────────────────────────────────────
        source_label = sp.get("label_a", "")
        source_id    = sp.get("id_a", "")
        target_label = sp.get("label_b", "")

        # ID propagation: fill empty source ID from prior sub-problem results.
        # Cap at 20 IDs per hop to prevent chain explosion on large result sets.
        _CHAIN_ID_CAP = 20
        if not source_id and source_label in produced_ids:
            source_ids = produced_ids[source_label][:_CHAIN_ID_CAP]
        elif source_id:
            source_ids = [source_id]
        else:
            source_ids = [""]

        sp_desc       = sp.get("description", "")
        is_last_sp    = (sp_id == sub_problems[-1]["id"]) if sub_problems else False
        # Last sub-problem of a chain inherits the original question's analytical
        # intent even if the LLM described it without analytical keywords.
        sp_analytical = _is_analytical(sp_desc) or (is_last_sp and _is_analytical(original_q))
        ner_sp        = ner.extract_entities(sp_desc) if sp_desc else None

        all_rows: list = []
        all_pivot_ids: set = set()

        # Analytical sub-problems only need one source ID to find the primitive
        iter_ids = source_ids[:1] if sp_analytical else source_ids

        for src_id in iter_ids:
            # Build pairs: real source first, then NER instances, then type hints
            pairs: list[tuple[str, str]] = []
            seen_lbl: set[str] = set()

            if source_label and src_id:
                pairs.append((source_label, src_id)); seen_lbl.add(source_label)

            if ner_sp:
                for lbl, val, _ in ner_sp.get("node_instance_pairs", []):
                    if lbl and val and lbl not in seen_lbl:
                        pairs.append((lbl, val)); seen_lbl.add(lbl)
                for lbl, score in ner_sp.get("node_labels", []):
                    if score >= 0.5 and lbl and lbl not in seen_lbl:
                        pairs.append((lbl, "")); seen_lbl.add(lbl)

            # Fallback struct labels as type hints
            for lbl in [source_label, target_label]:
                if lbl and lbl not in seen_lbl:
                    pairs.append((lbl, "")); seen_lbl.add(lbl)

            if not pairs:
                continue

            pr = plan_query(pairs)

            if sp_analytical and pr["deterministic"]:
                # ANALYTICAL: LLM modifies primitive RETURN clause for COUNT/sort/etc.
                # For the last sub-problem, use original_q so the LLM sees the user's
                # analytical intent (e.g. "how many") even if sp_desc lacks that phrasing.
                analytical_q = original_q if is_last_sp else sp_desc
                ans = _run_analytical_on_primitive(
                    analytical_q, pr["cypher"], pr.get("params", {}), tool_calls
                )
                analytical_answers.append(ans)
                break  # one primitive call is enough for analytical

            elif pr["deterministic"] and pr["ok"]:
                _pr_rows = pr["data"]
                _pr_previews = []
                for _r in _pr_rows[:10]:
                    _ids = [
                        f"{k}: {v.get('identifier', v.get('name', str(v)))}"
                        if isinstance(v, dict) else f"{k}: {v}"
                        for k, v in _r.items()
                    ]
                    _pr_previews.append(" | ".join(_ids))
                _pr_summary = (
                    f"{len(_pr_rows)} rows via {pr['primitive_key']}"
                    + ("\n" + "\n".join(_pr_previews) if _pr_previews else "")
                )
                tool_calls.append({
                    "tool": "plan_and_query",
                    "args": {"pairs": str(pairs), "primitive_key": pr["primitive_key"]},
                    "result_summary": _pr_summary,
                })
                rows = pr["data"]
            else:
                fallback_src = pairs[0][0] if pairs else source_label
                fallback_id  = pairs[0][1] if pairs else src_id
                fallback_tgt = target_label or (pairs[-1][0] if len(pairs) > 1 else "")
                result_str   = dispatch("execute_cypher", {
                    "query": (
                        f"MATCH (a:`{fallback_src}` {{identifier: $a_id}})"
                        f"-[*1..3]-(b:`{fallback_tgt}`) "
                        "RETURN properties(a) AS props_a, properties(b) AS props_b, "
                        "labels(b)[0] AS b_label"
                    ),
                    "params": {"a_id": fallback_id},
                })
                tool_calls.append({
                    "tool": "execute_cypher",
                    "args": {"label_a": fallback_src, "label_b": fallback_tgt},
                    "result_summary": result_str[:300],
                })
                try:
                    rows = json.loads(result_str).get("data", [])
                except Exception:
                    rows = []

            all_rows.extend(rows)

            # Collect IDs for all entity labels produced — feed later sub-problems
            for row in rows:
                if not isinstance(row, dict):
                    continue
                for lbl, node in row.items():
                    if isinstance(node, dict) and "identifier" in node:
                        nid = str(node["identifier"])
                        produced_ids.setdefault(lbl, [])
                        if nid not in produced_ids[lbl]:
                            produced_ids[lbl].append(nid)
                        if lbl == pivot_entity:
                            all_pivot_ids.add(nid)

        sub_data[sp_id]    = all_rows if not sp_analytical else []
        sub_results[sp_id] = all_pivot_ids if not sp_analytical else set()
        if not sp_analytical and sp_desc:
            relational_descs.append(sp_desc)

    # ── Early return when analytical answers cover the multi-part question ─────
    if analytical_answers:
        relational_rows = [row for rows in sub_data.values() for row in rows[:5]]
        if relational_rows:
            # Summarize only what the relational sub-problems actually retrieved,
            # so the LLM doesn't try to answer the analytical parts from partial data.
            rel_q = " AND ".join(relational_descs) if relational_descs else original_q
            rel_summary = _summarize_graph_result(
                rel_q, {"ok": True, "data": relational_rows}
            )
            answer = rel_summary + "\n\n" + "\n\n".join(analytical_answers)
        else:
            answer = "\n\n".join(analytical_answers)
        return _append_independent_answers(answer, independent_sps, summary_q, tool_calls)

    # ── Step 3: Logic tree evaluation ─────────────────────────────────────────
    def _eval_tree(node: dict) -> set:
        op = node.get("op", "LEAF")
        if op == "LEAF":
            return sub_results.get(node.get("step_id", ""), set())
        if op == "AND":
            result_set = None
            for operand in node.get("operands", []):
                s = _eval_tree(operand)
                result_set = s if result_set is None else result_set & s
            return result_set or set()
        if op == "OR":
            result_set: set = set()
            for operand in node.get("operands", []):
                result_set |= _eval_tree(operand)
            return result_set
        if op == "NOT":
            all_rows = neo4j_service.safe_run(
                f"MATCH (n:`{pivot_entity}`) RETURN n.identifier AS identifier"
            )
            all_ids = {
                str(r["identifier"])
                for r in all_rows.get("data", [])
                if r.get("identifier")
            }
            operands = node.get("operands", [])
            exclude_ids = _eval_tree(operands[0]) if operands else set()
            return all_ids - exclude_ids
        return set()

    # For chain queries the sequential ID propagation already filters results;
    # AND-intersecting across sub-problems that have no pivot-entity rows (e.g.
    # the middle Plan→Order step has no Vehicle rows) collapses to empty set.
    # Use the last sub-problem's pivot IDs directly for chains.
    if exec_pattern == "CHAIN" and sub_problems:
        last_sp_id = sub_problems[-1]["id"]
        combined_ids = sub_results.get(last_sp_id, set())
    else:
        combined_ids = _eval_tree(logic_tree)

    # ── Step 3: Answer from combined_ids ──────────────────────────────────────
    # For count queries: combined_ids already holds the exact set — no detail
    # fetch needed.  For retrieval queries: fetch details for up to 20 pivot IDs.
    q_lower = original_q.lower()
    is_count_query = any(k in q_lower for k in ("how many", "count", "total", "number of"))

    if is_count_query and (combined_ids or pivot_entity):
        count = len(combined_ids)
        answer = (
            f"There {'is' if count == 1 else 'are'} **{count}** "
            f"{pivot_entity}(s) matching the query."
        )
        return _append_independent_answers(answer, independent_sps, summary_q, tool_calls)

    # For chain queries: the sequential execution already captured the full
    # A→B→C context in sub_data. Using combined_ids→get_entity_details only
    # fetches the endpoint node's properties (e.g. ManufacturingPlant), losing
    # the intermediate AssemblyShop rows from step 1.
    if exec_pattern == "CHAIN":
        combined_rows = [row for rows in sub_data.values() for row in rows[:10]]
    else:
        combined_rows = []
        for pid in list(combined_ids)[:20]:
            detail_str = dispatch("get_entity_details", {
                "entity_type": pivot_entity,
                "identifier":  pid,
            })
            try:
                combined_rows.extend(json.loads(detail_str).get("data", []))
            except Exception:
                pass
        if not combined_rows:
            combined_rows = [row for rows in sub_data.values() for row in rows[:10]]

    answer = _summarize_graph_result(summary_q, {"ok": True, "data": combined_rows})
    return _append_independent_answers(answer, independent_sps, summary_q, tool_calls)


def _append_independent_answers(
    main_answer: str,
    independent_sps: list,
    summary_q: str,
    tool_calls: list,
) -> tuple[str, list[dict]]:
    """
    Execute independent sub-problems (those the user marked as independent in the HITL UI)
    and append their answers after the main linked answer, separated by "---".

    Each SP is executed as:
      one_node  → _execute_single_node_query
      two_node  → plan_query (primitive lookup), fallback to tool loop
    """
    if not independent_sps:
        return main_answer, tool_calls

    parts: list[str] = [main_answer] if main_answer else []

    for sp in independent_sps:
        lbl_a   = sp.get("label_a", "")
        id_a    = sp.get("id_a", "")
        lbl_b   = sp.get("label_b", "")
        id_b    = sp.get("id_b", "")
        sp_desc = sp.get("description", summary_q)

        if sp.get("type") == "two_node" and lbl_b:
            src_lbl, src_id, tgt_lbl, tgt_id = lbl_a, id_a, lbl_b, id_b
            if not src_id and tgt_id:
                src_lbl, src_id, tgt_lbl, tgt_id = lbl_b, id_b, lbl_a, id_a
            prim_r = plan_query([(src_lbl, src_id), (tgt_lbl, tgt_id)])
            if prim_r.get("deterministic") and prim_r.get("ok"):
                sp_ans = _summarize_graph_result(sp_desc, prim_r)
                _sp_rows = prim_r.get("data", [])
                _sp_previews = []
                for _r in _sp_rows[:10]:
                    _ids = [
                        f"{k}: {v.get('identifier', v.get('name', str(v)))}"
                        if isinstance(v, dict) else f"{k}: {v}"
                        for k, v in _r.items()
                    ]
                    _sp_previews.append(" | ".join(_ids))
                tool_calls.append({
                    "tool": "plan_and_query",
                    "args": {"primitive_key": prim_r["primitive_key"]},
                    "result_summary": (
                        f"{len(_sp_rows)} rows\n" + "\n".join(_sp_previews)
                        if _sp_previews else f"{len(_sp_rows)} rows"
                    ),
                })
            else:
                sp_ans, sp_tc, _ = _run_tool_loop(
                    sp_desc, sp_desc, None, [],
                    [(src_lbl, src_id), (tgt_lbl, "")],
                    {}, "default", 4,
                )
                tool_calls.extend(sp_tc)
            header = f"**{src_lbl}** `{src_id}` → **{tgt_lbl}**"
        else:
            sp_ans, sp_tc, _ = _execute_single_node_query(lbl_a, id_a, sp_desc)
            tool_calls.extend(sp_tc)
            header = f"**{lbl_a}**" + (f" `{id_a}`" if id_a else "")

        parts.append(f"{header}\n\n{sp_ans}")

    return "\n\n---\n\n".join(parts), tool_calls


# ── Tool loop (fallback for RELATIONAL 2-entity without matching primitive) ───

def _build_entity_schema(entity_pairs: list) -> str:
    """Extract live KG sub-schema for the entity labels involved in this query.

    Queries the actual 2-hop neighborhood of specific node instances in the live graph,
    so the schema is bounded by real data topology rather than the full static schema graph.
    Falls back to 1-hop static BFS for type-hint (empty-ID) pairs.
    """
    if not entity_pairs:
        return SCHEMA_SUMMARY
    sub = kg_schema_service.get_instance_neighborhood_schema(entity_pairs, hops=2)
    return sub if sub else SCHEMA_SUMMARY


def _run_tool_loop(
    question: str,
    rewritten_question: str,
    clicked_entity: dict | None,
    working_set: list[dict],
    entity_pairs: list,
    session_state: dict,
    session_id: str,
    max_tool_rounds: int,
    primitive_hint: str = "",
) -> tuple[str, list[dict], list[dict], str, str]:
    """Returns (answer, tool_calls, result_entities, intent, reasoning)."""
    classification = intent_classifier.classify(rewritten_question, clicked_entity)
    intent = classification.get("category", "specific")

    click_str = "None selected."
    if clicked_entity:
        click_str = (
            f"{clicked_entity.get('type', '')} — "
            f"{clicked_entity.get('identifier', '')} "
            f"(props: {json.dumps(clicked_entity.get('properties', {}))[:200]})"
        )

    mem_str = "\n".join(
        f"  - [{e['source']}|ttl={e['ttl']}] {e['label']}: {e['id']}"
        for e in working_set
    ) if working_set else ""

    session_ctx = memory_service.get_session_context(session_id, last_n=5)
    session_ctx_str = "\n".join(
        f"  - [{e.get('event_type','')}] {e.get('content','')[:80]}"
        for e in session_ctx
    )

    entity_schema = _build_entity_schema(entity_pairs)
    system_prompt = f"""You are an automotive manufacturing KBS assistant.
Use tools to retrieve data from the Neo4j knowledge graph before answering.

KG schema relevant to this query:
{entity_schema}

Date/time handling rules (IMPORTANT):
- All date/time values in Neo4j are stored as strings in format 'YYYY-MM-DD HH:MM:SS'
  e.g. '2015-10-01 00:00:00'
- Check the schema above to find the correct date/time property name for the node
  (e.g. plannedStartTime, startTime, endTime, createTime, validFrom, etc.)
- For Plan/Order nodes the date properties are on their Version node (via CURRENT_VERSION):
    MATCH (pp:ProductionPlan)-[:CURRENT_VERSION]->(v:ProductionPlanVersion)
    WHERE v.plannedStartTime >= '...' AND v.plannedStartTime < '...'
- When filtering by date, choose a range comparison:
    day   → prop >= 'YYYY-MM-DD 00:00:00' AND prop < 'YYYY-MM-DD+1 00:00:00'
    month → prop >= 'YYYY-MM-01 00:00:00' AND prop < 'YYYY-MM+1-01 00:00:00'
    year  → prop >= 'YYYY-01-01 00:00:00' AND prop < 'YYYY+1-01-01 00:00:00'
- Always use string comparison (not date() conversion) since values are plain strings.

Current context:
- Clicked entity (Tier 1): {click_str}
- Intent: {intent}
- Entity working set (Tier 3):
{mem_str or '  (empty)'}
- Recent session activity:
{session_ctx_str or '  (none)'}

Answer concisely, citing specific identifiers from query results.
Use plan_and_query for two-entity queries; execute_cypher for single-node or aggregations.
{f'''
Primitive traversal path for this query (use as base Cypher — modify to add COUNT, ORDER BY, filters, etc.):
{primitive_hint}
Use execute_cypher with a modified version of the above Cypher.
''' if primitive_hint else ''}"""

    history = memory_service.get_conversation_history(session_state, last_n=10)
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": rewritten_question})

    tool_calls_made: list[dict] = []
    result_entities: list[dict] = []
    client = _get_client()
    answer = ""

    _clicked = context_manager.get_clicked_entity()
    _clicked_key = (
        (_clicked.get("type", ""), _clicked.get("identifier", ""))
        if _clicked else ("", "")
    )
    _seen_calls: set[tuple] = set()  # dedup identical (tool_name, args_json) within this loop

    for _round in range(max_tool_rounds):
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            tools=TOOL_DEFINITIONS,
            tool_choice="auto",
        )
        _acc_tokens(response.usage)
        msg = response.choices[0].message

        if not msg.tool_calls:
            answer = msg.content or ""
            break

        messages.append(msg)
        for tc in msg.tool_calls:
            tool_name = tc.function.name
            try:
                tool_args = json.loads(tc.function.arguments)
            except Exception:
                tool_args = {}

            # Skip exact duplicate calls (same tool + same args) within this loop
            _call_key = (tool_name, json.dumps(tool_args, sort_keys=True))
            if _call_key in _seen_calls:
                messages.append({
                    "role":         "tool",
                    "tool_call_id": tc.id,
                    "content":      json.dumps({"ok": True, "note": "duplicate call skipped — use previous result"}),
                })
                continue
            _seen_calls.add(_call_key)

            result_str = dispatch(tool_name, tool_args)
            tool_calls_made.append({
                "tool":           tool_name,
                "args":           tool_args,
                "result_summary": result_str[:300],
            })
            messages.append({
                "role":         "tool",
                "tool_call_id": tc.id,
                "content":      result_str,
            })
            for e in _extract_result_entities(tool_name, tool_args, result_str):
                if (e["label"], e["id"]) != _clicked_key:
                    result_entities.append(e)
    else:
        answer = "Reached maximum tool rounds. Please try a more specific question."

    return answer, tool_calls_made, result_entities, intent, classification.get("reasoning", "")


# ── RELATIONAL 2-entity execution (shared by Scenario B and HITL handler) ─────

def _execute_relational_query(
    entity_pairs: list,
    question: str,
    rewritten_question: str,
    time_filter: dict | None,
    decomp_fallback: str | None,
    clicked_entity: dict | None,
    working_set: list,
    session_state: dict,
    session_id: str,
    max_tool_rounds: int,
) -> tuple[str, list[dict], list[dict], str, str]:
    """Execute a 2-entity RELATIONAL query: primitive → LLM/analytical → tool loop.
    Returns (answer, tool_calls, result_entities, intent, reasoning).
    """
    tool_calls: list[dict] = []
    result_entities: list[dict] = []
    intent = "specific"

    plan_result = plan_query(entity_pairs)
    if plan_result["deterministic"] and plan_result["ok"]:
        needs_llm = _is_analytical(rewritten_question) or bool(time_filter)
        if needs_llm:
            hint = (
                f"  Key:    {plan_result['primitive_key']}\n"
                f"  Cypher: {plan_result['cypher']}"
            )
            if time_filter:
                hint += (
                    f"\n  Time filter ({time_filter.get('type','')}):"
                    f"  start={time_filter.get('start','')}, end={time_filter.get('end','')}"
                    f"\n  Add WHERE on a timestamp property of the path using:"
                    f"\n    prop >= '{time_filter.get('start','')}' AND prop < '{time_filter.get('end','')}'"
                )
            answer, tool_calls, result_entities, intent, reasoning = _run_tool_loop(
                question, rewritten_question,
                clicked_entity, working_set, entity_pairs,
                session_state, session_id, max_tool_rounds,
                primitive_hint=hint,
            )
            mode = "time-filtered" if time_filter and not _is_analytical(rewritten_question) else "analytical"
            reasoning = f"2-entity RELATIONAL, {mode}: {plan_result['primitive_key']} → LLM Cypher"
            if decomp_fallback:
                reasoning += f" ({decomp_fallback})"
        else:
            answer    = _summarize_graph_result(rewritten_question, plan_result)
            reasoning = f"2-entity RELATIONAL, deterministic: {plan_result['primitive_key']}"
            if decomp_fallback:
                reasoning += f" ({decomp_fallback})"
            tool_calls = [{
                "tool": "plan_and_query",
                "args": {
                    "primitive_key": plan_result["primitive_key"],
                    "entity_pairs":  str(entity_pairs),
                },
                "result_summary": f"{len(plan_result['data'])} rows",
            }]
            fake = json.dumps({"data": plan_result.get("data", [])})
            result_entities = _extract_result_entities("plan_and_query", {}, fake)
    else:
        hint = ""
        if plan_result["deterministic"]:
            tool_calls.append({
                "tool": "plan_and_query",
                "args": {
                    "primitive_key": plan_result["primitive_key"],
                    "entity_pairs":  str(entity_pairs),
                },
                "result_summary": (
                    f"ok={plan_result['ok']} rows={len(plan_result.get('data', []))}"
                    + (f" error={plan_result['error']}" if plan_result.get("error") else "")
                ),
            })
            hint = (
                f"  Key:    {plan_result['primitive_key']}\n"
                f"  Cypher: {plan_result['cypher']}"
            )
        _answer, _tc, result_entities, intent, reasoning = _run_tool_loop(
            question, rewritten_question,
            clicked_entity, working_set, entity_pairs,
            session_state, session_id, max_tool_rounds,
            primitive_hint=hint,
        )
        answer = _answer
        tool_calls.extend(_tc)
        if decomp_fallback:
            reasoning = f"{reasoning} ({decomp_fallback})" if reasoning else f"decomposability fallback: {decomp_fallback}"

    return answer, tool_calls, result_entities, intent, reasoning


# ── HITL: pending confirmation handlers ───────────────────────────────────────

def _execute_subtask(sub_task: dict, tool_calls_out: list, session_state: dict) -> str:
    """
    Execute one confirmed sub-task from a question_split pending.

    Reads sub_task["sub_problems"] (pre-built / user-edited) and sub_task["logic_op"]:
      - No sub_problems or single sub-problem (logic_op=None): plan_query or single-node lookup
      - Multiple sub-problems + logic_op (OR|AND): calls _execute_decomposition
    Returns an answer string.
    """
    q        = sub_task.get("question", "")
    logic_op = sub_task.get("logic_op")       # None | "OR" | "AND"
    tgt_lbl  = sub_task.get("label", "")
    sps      = [sp for sp in sub_task.get("sub_problems", []) if not sp.get("independent")]

    _session_id      = session_state.get("session_id", "default")
    _max_tool_rounds = 6

    if not sps:
        # No linked sub-problems: try a single-entity lookup via NER on the question
        _ner   = ner.extract_entities(q)
        _pairs = [
            (_VERSION_SPEC_NORM_GLOBAL.get(l, l), i)
            for l, i in [(p[0], p[1]) for p in _ner.get("node_instance_pairs", [])]
        ]
        _real  = [(l, i) for l, i in _pairs if i and re.search(r"[0-9\-]", i)]
        if not _real:
            ans, tc, _, _, _ = _run_tool_loop(
                q, q, None, [], [], session_state, _session_id, _max_tool_rounds
            )
            tool_calls_out.extend(tc)
            return ans
        al, ai = _real[0]
        tgt    = tgt_lbl or (
            [l for l, i in _pairs if not i][0] if [l for l, i in _pairs if not i] else ""
        )
        prim_r = plan_query([(al, ai)] + ([(tgt, "")] if tgt else []))
        if prim_r.get("ok"):
            tool_calls_out.append({
                "tool": "plan_and_query",
                "args": {"pairs": str([(al, ai)])},
                "result_summary": f"{len(prim_r.get('data', []))} rows",
            })
            return _summarize_graph_result(q, prim_r)
        ans2, tc2, _ = _execute_single_node_query(al, ai, q)
        tool_calls_out.extend(tc2)
        return ans2

    if len(sps) == 1 and logic_op in (None, "CHAIN"):
        # Single linked sub-problem with no set-op
        sp  = sps[0]
        al  = sp.get("label_a", "")
        ai  = sp.get("id_a", "")
        tgt = sp.get("label_b", "") or tgt_lbl
        # one_node sps → always single-entity lookup (no target label to traverse to)
        if sp.get("type") == "one_node" or not tgt:
            ans3, tc3, _ = _execute_single_node_query(al, ai, q)
            tool_calls_out.extend(tc3)
            return ans3
        if not ai:
            ans3, tc3, _ = _execute_single_node_query(al, ai, q)
            tool_calls_out.extend(tc3)
            return ans3
        prim_r2 = plan_query([(al, ai), (tgt, "")])
        if prim_r2.get("ok"):
            tool_calls_out.append({
                "tool": "plan_and_query",
                "args": {"pairs": str([(al, ai), (tgt, "")])},
                "result_summary": f"{len(prim_r2.get('data', []))} rows",
            })
            return _summarize_graph_result(q, prim_r2)
        ans4, tc4, _ = _execute_single_node_query(al, ai, q)
        tool_calls_out.extend(tc4)
        return ans4

    # Multi-linked sub-problems → _execute_decomposition
    # CHAIN → pass edited_pattern="CHAIN" so _detect_pattern returns "CHAIN" and
    #          _execute_decomposition uses Step 2 sequential ID-propagation.
    # OR / AND → set-op logic tree.
    _edited_pat = logic_op if logic_op in ("CHAIN", "OR", "AND") else "CHAIN"
    _pivot = tgt_lbl or (sps[-1].get("label_b", "") or sps[0].get("label_b", "") if sps else "")
    mini_pending = {
        "sub_problems":       sps,
        "logic_tree":         {"op": "AND" if _edited_pat == "CHAIN" else _edited_pat},
        "pivot_entity":       _pivot,
        "edited_pattern":     _edited_pat,
        "original_question":  q,
        "rewritten_question": q,
        "description":        sub_task.get("question", ""),
    }
    ans5, tcs = _execute_decomposition(mini_pending)
    tool_calls_out.extend(tcs)
    return ans5


# Module-level alias so _execute_subtask can access the norm map without
# needing it re-declared inside process_question's local scope.
_VERSION_SPEC_NORM_GLOBAL: dict[str, str] = {
    "ProductionOrderVersion": "ProductionOrder",
    "ProductionPlanVersion":  "ProductionPlan",
    "ProductionOrderSpec":    "ProductionOrder",
    "ProductionPlanSpec":     "ProductionPlan",
    "OperationVersion":       "Operation",
    "WorkStepVersion":        "WorkStep",
    "PartSpec":               "Part",
    "EquipmentSpec":          "Equipment",
    "WorkStepSpec":           "WorkStep",
    "OperationSpec":          "Operation",
    "ManualToolSpec":         "ManualTool",
    "PrecisionToolSpec":      "PrecisionTool",
    "DiagnosticEquipment":          "Equipment",
    "RoboticEquipment":             "Equipment",
    "ProcessEquipment":             "Equipment",
    "MaterialHandlingEquipment":    "Equipment",
    "DiagnosticEquipmentSpec":      "Equipment",
    "ProcessEquipmentSpec":         "Equipment",
    "RoboticEquipmentSpec":         "Equipment",
    "MaterialHandlingEquipmentSpec":"Equipment",
    "DiagnosticEquipmentInstance":  "Equipment",
    "RoboticEquipmentInstance":     "Equipment",
    "ProcessEquipmentInstance":     "Equipment",
    "MaterialHandlingEquipmentInstance": "Equipment",
    "VehicleVariantSpecification":  "VehicleVariant",
    "VehicleVariantSpec":           "VehicleVariant",
}


def handle_confirmation(confirmed: bool, session_state: dict) -> dict:
    """
    Handle HITL confirmation from UI buttons.
    Always clears pending_confirmation before acting.
    """
    session_state["_active_request_id"] = uuid.uuid4().hex[:8]
    pending = session_state.get("pending_confirmation") or {}
    ptype   = pending.get("type", "")

    memory_service.set_pending_confirmation(session_state, None)

    if not confirmed:
        msg = "Please simplify your question or break it into smaller parts."
        memory_service.append_message(session_state, "assistant", msg)
        return _build_result(
            msg, "specific", "", [], "User rejected confirmation.", {},
            memory_service.get_entity_working_set(session_state),
        )

    # confirmed = True

    if ptype == "question_split":
        confirmed_sub_tasks = pending.get("sub_tasks", [])
        session_id_qs = session_state.get("session_id", "default")
        all_answers:    list[str]  = []
        all_tool_calls: list[dict] = []

        for _st_item in confirmed_sub_tasks:
            _ans = _execute_subtask(_st_item, all_tool_calls, session_state)
            all_answers.append(_ans)

        combined_qs = "\n\n---\n\n".join(a for a in all_answers if a)
        wset_qs = memory_service.get_entity_working_set(session_state)
        _meta_qs = {
            "rewritten_question": pending.get("original_question", ""),
            "ner_context":        {},
            "tool_calls_made":    all_tool_calls,
            "reasoning":          "Compound question split and executed.",
            "working_set":        wset_qs,
            "intent":             "high_level",
        }
        memory_service.append_message(session_state, "assistant", combined_qs, metadata=_meta_qs)
        memory_service.record_interaction(
            session_id=session_id_qs,
            event_type="HITL_CONFIRM",
            content=f"question_split: {len(confirmed_sub_tasks)} sub-tasks",
            resolved_intent="high_level",
        )
        return {
            "answer":             combined_qs,
            "intent":             "high_level",
            "rewritten_question": pending.get("original_question", ""),
            "tool_calls_made":    all_tool_calls,
            "reasoning":          "Compound question split and executed.",
            "ner_context":        {},
            "working_set":        wset_qs,
        }

    if ptype == "complex_decomposition":
        answer, tool_calls = _execute_decomposition(pending)
        session_id = session_state.get("session_id", "default")
        wset_after = memory_service.get_entity_working_set(session_state)
        _rewritten = pending.get("rewritten_question") or pending.get("original_question", "")
        try:
            ner_r = ner.extract_entities(_rewritten) if _rewritten else {}
        except Exception:
            ner_r = {}
        _meta = {
            "rewritten_question": _rewritten,
            "ner_context":        ner_r,
            "tool_calls_made":    tool_calls,
            "reasoning":          "Complex decomposition confirmed by user.",
            "working_set":        wset_after,
            "intent":             "high_level",
        }
        memory_service.append_message(session_state, "assistant", answer, metadata=_meta)
        memory_service.record_interaction(
            session_id=session_id,
            event_type="HITL_CONFIRM",
            content=pending.get("description", "")[:500],
            resolved_intent="high_level",
        )
        return {
            "answer":             answer,
            "intent":             "high_level",
            "rewritten_question": _rewritten,
            "tool_calls_made":    tool_calls,
            "reasoning":          "Complex decomposition confirmed by user.",
            "ner_context":        ner_r,
            "working_set":        wset_after,
        }

    if ptype == "independent_decomposition":
        ep          = pending.get("entity_pairs", [])
        rewritten_q = pending.get("rewritten_question", pending.get("original_question", ""))
        session_id  = session_state.get("session_id", "default")
        parts_ind: list[str] = []
        tool_calls_out: list[dict] = []
        result_entities_out: list[dict] = []

        for lbl, eid in ep:
            ans_part, tc_part, re_part = _execute_single_node_query(lbl, eid, rewritten_q)
            parts_ind.append(ans_part)
            tool_calls_out.extend(tc_part)
            result_entities_out.extend(re_part)

        answer_ind = "\n\n---\n\n".join(parts_ind)
        fallback   = pending.get("decomp_fallback")
        reasoning_out = "2-entity INDEPENDENT confirmed by user." + (f" ({fallback})" if fallback else "")

        _clicked     = context_manager.get_clicked_entity()
        _clicked_key = (
            (_clicked.get("type", ""), _clicked.get("identifier", "")) if _clicked else ("", "")
        )
        new_ents = [e for e in result_entities_out if (e["label"], e["id"]) != _clicked_key]
        memory_service.upsert_entities(session_state, new_ents)

        wset_after = memory_service.get_entity_working_set(session_state)
        try:
            ner_r_ind = ner.extract_entities(rewritten_q) if rewritten_q else {}
        except Exception:
            ner_r_ind = {}
        _meta = {
            "rewritten_question": rewritten_q,
            "ner_context":        ner_r_ind,
            "tool_calls_made":    tool_calls_out,
            "reasoning":          reasoning_out,
            "working_set":        wset_after,
            "intent":             "specific",
        }
        memory_service.append_message(session_state, "assistant", answer_ind, metadata=_meta)
        memory_service.record_interaction(
            session_id=session_id,
            event_type="HITL_CONFIRM",
            content=pending.get("description", "")[:500],
            resolved_intent="specific",
        )
        return {
            "answer":             answer_ind,
            "intent":             "specific",
            "rewritten_question": rewritten_q,
            "tool_calls_made":    tool_calls_out,
            "reasoning":          reasoning_out,
            "ner_context":        ner_r_ind,
            "working_set":        wset_after,
        }

    if ptype == "relational_decomposition":
        rewritten_q = pending.get("rewritten_question", pending.get("original_question", ""))
        session_id  = session_state.get("session_id", "default")
        answer, tc, result_entities, intent_r, reasoning_r = _execute_relational_query(
            pending.get("entity_pairs", []),
            pending.get("original_question", ""),
            rewritten_q,
            pending.get("time_filter"),
            pending.get("decomp_fallback"),
            context_manager.get_clicked_entity(),
            memory_service.get_entity_working_set(session_state),
            session_state, session_id, 6,
        )
        try:
            ner_r = ner.extract_entities(rewritten_q) if rewritten_q else {}
        except Exception:
            ner_r = {}
        _clicked     = context_manager.get_clicked_entity()
        _clicked_key = (
            (_clicked.get("type", ""), _clicked.get("identifier", "")) if _clicked else ("", "")
        )
        new_ents = [e for e in result_entities if (e["label"], e["id"]) != _clicked_key]
        memory_service.upsert_entities(session_state, new_ents)
        wset_after = memory_service.get_entity_working_set(session_state)
        _meta = {
            "rewritten_question": rewritten_q,
            "ner_context":        ner_r,
            "tool_calls_made":    tc,
            "reasoning":          reasoning_r,
            "working_set":        wset_after,
            "intent":             intent_r,
        }
        memory_service.append_message(session_state, "assistant", answer, metadata=_meta)
        memory_service.record_interaction(
            session_id=session_id,
            event_type="HITL_CONFIRM",
            content=pending.get("description", "")[:500],
            resolved_intent=intent_r,
        )
        return {
            "answer":             answer,
            "intent":             intent_r,
            "rewritten_question": rewritten_q,
            "tool_calls_made":    tc,
            "reasoning":          reasoning_r,
            "ner_context":        ner_r,
            "working_set":        wset_after,
        }

    if ptype == "condition_confirmation":
        _meta = _request_log_meta(session_state)
        logger.warning(
            f"processing condition confirmation request_id={_meta['request_id']} session_id={_meta['session_id']}",
            extra={
                "stage": "condition_confirmation_process",
                "confirmed": confirmed,
                "original_question": _clip_for_log(pending.get("original_question", "")),
                "rewritten_question": _clip_for_log(pending.get("rewritten_question", "")),
                "entity_pairs": _clip_for_log(str(pending.get("entity_pairs", []))),
                "time_conditions": _clip_for_log(json.dumps(pending.get("time_conditions", []), default=str)),
                "property_conditions": _clip_for_log(json.dumps(pending.get("property_conditions", []), default=str)),
                **_meta,
            },
        )
        if not confirmed:
            # User cancelled — re-run the query WITHOUT conditions
            answer, tool_calls = _execute_with_conditions(pending, [], [], session_state)
            rewritten_q = pending.get("rewritten_question", "")
            try:
                ner_result_cancel = ner.extract_entities(rewritten_q) if rewritten_q else {}
            except Exception:
                ner_result_cancel = {}
            prefix = f"**Interpreted as:** _{rewritten_q}_\n\n" if rewritten_q else ""
            msg = prefix + (answer or "Query executed without condition filters.")
            wset_after = memory_service.get_entity_working_set(session_state)
            _meta = {
                "rewritten_question": rewritten_q,
                "ner_context":        ner_result_cancel,
                "tool_calls_made":    tool_calls,
                "reasoning":          "Condition confirmation cancelled — query run without filters.",
                "working_set":        wset_after,
                "intent":             "specific",
            }
            memory_service.append_message(session_state, "assistant", msg, metadata=_meta)
            return {
                "answer":             msg,
                "intent":             "specific",
                "rewritten_question": rewritten_q,
                "tool_calls_made":    tool_calls,
                "reasoning":          "Condition confirmation cancelled.",
                "ner_context":        ner_result_cancel,
                "working_set":        wset_after,
            }
        # confirmed=True — use the (possibly user-edited) confirmed conditions
        confirmed_time  = pending.get("confirmed_time_conditions")
        confirmed_props = pending.get("confirmed_property_conditions")
        if confirmed_time is None:
            confirmed_time  = pending.get("time_conditions", [])
        if confirmed_props is None:
            confirmed_props = pending.get("property_conditions", [])
        # Streamlit reruns can occasionally drop edited arrays to [] even when
        # extracted conditions existed. In that case, prefer the pending
        # extracted conditions over silently executing an unfiltered lookup.
        if (
            not confirmed_time and not confirmed_props
            and (pending.get("time_conditions") or pending.get("property_conditions"))
        ):
            confirmed_time  = pending.get("time_conditions", [])
            confirmed_props = pending.get("property_conditions", [])
        answer, tool_calls = _execute_with_conditions(
            pending, confirmed_time, confirmed_props, session_state
        )
        rewritten_q = pending.get("rewritten_question", "")
        # Run NER on the rewritten question so the context panel shows extracted entities
        try:
            ner_result_confirm = ner.extract_entities(rewritten_q) if rewritten_q else {}
        except Exception:
            ner_result_confirm = {}
        prefix = f"**Interpreted as:** _{rewritten_q}_\n\n" if rewritten_q else ""
        msg = prefix + (answer or "Query executed with confirmed conditions.")
        session_id = pending.get("session_id", "default")
        wset_after = memory_service.get_entity_working_set(session_state)
        _meta = {
            "rewritten_question": rewritten_q,
            "ner_context":        ner_result_confirm,
            "tool_calls_made":    tool_calls,
            "reasoning":          "Condition confirmation accepted by user.",
            "working_set":        wset_after,
            "intent":             "specific",
        }
        memory_service.append_message(session_state, "assistant", msg, metadata=_meta)
        memory_service.record_interaction(
            session_id=session_id,
            event_type="HITL_CONFIRM",
            content=pending.get("description", "")[:500],
            resolved_intent="specific",
        )
        return {
            "answer":             msg,
            "intent":             "specific",
            "rewritten_question": rewritten_q,
            "tool_calls_made":    tool_calls,
            "reasoning":          "Condition confirmation accepted by user.",
            "ner_context":        ner_result_confirm,
            "working_set":        wset_after,
        }

    msg = "No pending action to confirm."
    return _build_result(msg, "specific", "", [], "", {},
                         memory_service.get_entity_working_set(session_state))


def _interpret_and_handle_pending(question: str, session_state: dict) -> dict:
    """Text-input fallback: parse yes/no and call handle_confirmation."""
    q_lower = question.lower().strip()
    yes_tokens = {"yes", "confirm", "correct", "ok", "sure", "proceed", "right", "go"}
    no_tokens  = {"no", "cancel", "wrong", "incorrect", "reject", "stop", "different", "not"}

    is_yes = any(tok in q_lower.split() for tok in yes_tokens)
    is_no  = any(tok in q_lower.split() for tok in no_tokens)

    if is_yes and not is_no:
        memory_service.append_message(session_state, "user", question)
        return handle_confirmation(True, session_state)
    if is_no and not is_yes:
        memory_service.append_message(session_state, "user", question)
        return handle_confirmation(False, session_state)

    # Ambiguous — re-show pending state
    pending      = session_state.get("pending_confirmation") or {}
    description  = pending.get("description", "")
    msg = (
        f"I'm waiting for your confirmation of the query plan:\n\n"
        f"> {description}\n\n"
        f"Click **✓ Confirm** or **✗ Reject**, or type 'yes'/'no'."
    )
    memory_service.append_message(session_state, "user", question)
    memory_service.append_message(session_state, "assistant", msg)
    return _build_result(
        msg, "specific", "", [], "Waiting for confirmation.",
        {}, memory_service.get_entity_working_set(session_state),
    )


# ── Main chat function ─────────────────────────────────────────────────────────

def chat(
    question: str,
    session_state: dict,
    max_tool_rounds: int = 6,
    enable_rewrite: bool = True,
) -> dict:
    """
    Process a user question through the HITL Resolution Waterfall pipeline.

    Returns:
        {
            "answer":             str,
            "intent":             str,
            "rewritten_question": str,
            "tool_calls_made":    list[dict],
            "reasoning":          str,
            "ner_context":        dict,
            "working_set":        list,
        }
    """
    session_id = session_state.get("session_id", "default")
    session_state["_active_request_id"] = uuid.uuid4().hex[:8]
    _reset_tokens()
    _meta = _request_log_meta(session_state)
    logger.warning(
        f"chat invoked request_id={_meta['request_id']} session_id={_meta['session_id']}",
        extra={
            "stage": "chat_entry",
            "question": _clip_for_log(question),
            "enable_rewrite": enable_rewrite,
            "has_pending_confirmation": bool(session_state.get("pending_confirmation")),
            **_meta,
        },
    )

    # ── Pending confirmation text fallback ────────────────────────────────────
    if session_state.get("pending_confirmation"):
        logger.warning(
            f"chat handling existing pending confirmation request_id={_meta['request_id']} session_id={_meta['session_id']}",
            extra={
                "stage": "pending_confirmation_entry",
                "question": _clip_for_log(question),
                **_meta,
            },
        )
        return _interpret_and_handle_pending(question, session_state)

    # ── Phase 1: NER + context layers ─────────────────────────────────────────
    ner_result    = ner.extract_entities(question)
    ner_pairs     = ner_result["node_instance_pairs"]
    ner_rewritten = ner_result["rewritten_query"]
    # NER may detect node label types (e.g. "Vehicle", "ProductionProcess") even
    # when no specific instance IDs are present (e.g. aggregate/date queries).
    # Also used to substitute canonical label names in the rewrite.
    node_labels   = ner_result.get("node_labels", [])  # [(label, score), ...]

    # Normalize spec/version sub-class labels to base labels so the rewrite prompt's
    # [Detected KG Labels] block uses canonical names (e.g. "VehicleVariant" not
    # "VehicleVariantSpecification"), preventing the LLM from substituting the
    # internal spec label into the rewritten question.
    _LABEL_NORM_EARLY = {
        "VehicleVariantSpecification":  "VehicleVariant",
        "VehicleVariantSpec":           "VehicleVariant",
        "PartSpec":                     "Part",
        "EquipmentSpec":                "Equipment",
        "WorkStepSpec":                 "WorkStep",
        "OperationSpec":                "Operation",
        "ManualToolSpec":               "ManualTool",
        "PrecisionToolSpec":            "PrecisionTool",
        # Equipment subtypes → Equipment (prevents NER2 subtype explosion after rewrite)
        "DiagnosticEquipment":          "Equipment",
        "RoboticEquipment":             "Equipment",
        "ProcessEquipment":             "Equipment",
        "MaterialHandlingEquipment":    "Equipment",
        # Equipment spec subtypes → Equipment
        "DiagnosticEquipmentSpec":      "Equipment",
        "ProcessEquipmentSpec":         "Equipment",
        "RoboticEquipmentSpec":         "Equipment",
        "MaterialHandlingEquipmentSpec":"Equipment",
        # EquipmentInstance subtypes → Equipment
        "DiagnosticEquipmentInstance":  "Equipment",
        "RoboticEquipmentInstance":     "Equipment",
        "ProcessEquipmentInstance":     "Equipment",
        "MaterialHandlingEquipmentInstance": "Equipment",
        "ProductionOrderSpec":          "ProductionOrder",
        "ProductionPlanSpec":           "ProductionPlan",
    }
    node_labels = [(_LABEL_NORM_EARLY.get(lbl, lbl), score) for lbl, score in node_labels]
    ner_pairs   = [(_LABEL_NORM_EARLY.get(lbl, lbl), *rest)  for lbl, *rest in ner_pairs]

    # Filter out NER pairs whose "identifier" contains no digits or hyphens.
    # Real KG entity IDs always contain at least one digit or hyphen (e.g. TFA2A,
    # MFT-D20, PO1015).  Pure-alpha strings like "SUPPORT" are English words that
    # the NER LLM mistakenly extracted (e.g. "qualified to support" → PartBatch:SUPPORT).
    ner_pairs = [(lbl, eid, *rest) for lbl, eid, *rest in ner_pairs
                 if re.search(r"[0-9\-]", eid)]

    clicked_entity = context_manager.get_clicked_entity()
    working_set    = memory_service.decay_entity_working_set(session_state)

    if enable_rewrite:
        rewrite_result       = _rewrite_question(
            ner_rewritten, clicked_entity, ner_pairs, working_set, node_labels
        )
        rewritten_question   = rewrite_result["rewritten"]
        _time_conditions     = rewrite_result.get("time_conditions") or []
        _property_conditions = rewrite_result.get("property_conditions") or []
        _any_conditions      = bool(_time_conditions or _property_conditions)
    else:
        rewritten_question   = ner_rewritten
        _time_conditions     = []
        _property_conditions = []
        _any_conditions      = False

    # ── Re-run NER on the rewritten question ─────────────────────────────────
    # The rewrite substitutes canonical label names and inlines explicit IDs,
    # so a second NER pass extracts much richer entity pairs for routing.
    # Use NER2 result for both routing AND UI display (context panel).
    ner_rewritten2 = ner.extract_entities(rewritten_question)
    ner_pairs      = ner_rewritten2["node_instance_pairs"]
    node_labels    = ner_rewritten2.get("node_labels", [])
    ner_result     = ner_rewritten2  # show NER2 in context panel

    # If NER2 found no instances but the rewriter embedded working-set entity IDs
    # into the question, inject those entities directly (their IDs appear literally
    # in the rewritten text because the rewriter placed them there).
    if not ner_pairs:
        for e in working_set:
            eid = e.get("id", "")
            if eid and eid in rewritten_question:
                ner_pairs.append((e.get("label", "Unknown"), eid, "identifier"))

    # ── Phase 1a: Clarity check ───────────────────────────────────────────────
    if not ner_pairs and not node_labels and not clicked_entity:
        msg = "Please provide more specific details."
        memory_service.append_message(session_state, "user", question)
        memory_service.append_message(session_state, "assistant", msg)
        return _build_result(
            msg, "specific", rewritten_question, [],
            "Clarity=unclear: no entity context.", ner_result,
            memory_service.get_entity_working_set(session_state),
        )

    # ── Phase 2: Entity count routing ─────────────────────────────────────────
    # Routing uses NER2 instance pairs ONLY — no clicked_entity injection.
    # Strategy: the clicked entity served its purpose during rewriting (it was
    # inlined as an explicit ID in the rewritten question). NER2 extracts that ID
    # from the rewrite text. For aggregate queries ("how many vehicles on date X?")
    # the rewrite has no specific instance ID, so entity_pairs stays empty and
    # routes to the tool loop — clicked entity only provides LLM context there.
    entity_pairs = resolve_entity_pairs(None, ner_pairs, [])

    # Normalize *Version/*Spec suffixes to base entity labels for primitive lookup.
    # e.g. ProductionOrderVersion → ProductionOrder, ProductionPlanSpec → ProductionPlan.
    # NER maps instance IDs to their version/spec sub-class; primitives use the base class.
    _VERSION_SPEC_NORM = {
        "ProductionOrderVersion": "ProductionOrder",
        "ProductionPlanVersion":  "ProductionPlan",
        "ProductionOrderSpec":    "ProductionOrder",
        "ProductionPlanSpec":     "ProductionPlan",
        "OperationVersion":       "Operation",
        "WorkStepVersion":        "WorkStep",
        "PartSpec":               "Part",
        "EquipmentSpec":          "Equipment",
        "WorkStepSpec":           "WorkStep",
        "OperationSpec":          "Operation",
        "ManualToolSpec":         "ManualTool",
        "PrecisionToolSpec":      "PrecisionTool",
        # Equipment subtypes → Equipment
        "DiagnosticEquipment":          "Equipment",
        "RoboticEquipment":             "Equipment",
        "ProcessEquipment":             "Equipment",
        "MaterialHandlingEquipment":    "Equipment",
        # Equipment spec subtypes → Equipment
        "DiagnosticEquipmentSpec":      "Equipment",
        "ProcessEquipmentSpec":         "Equipment",
        "RoboticEquipmentSpec":         "Equipment",
        "MaterialHandlingEquipmentSpec":"Equipment",
        # EquipmentInstance subtypes → Equipment
        "DiagnosticEquipmentInstance":  "Equipment",
        "RoboticEquipmentInstance":     "Equipment",
        "ProcessEquipmentInstance":     "Equipment",
        "MaterialHandlingEquipmentInstance": "Equipment",
        "VehicleVariantSpecification":  "VehicleVariant",
        "VehicleVariantSpec":           "VehicleVariant",
    }
    entity_pairs = [(_VERSION_SPEC_NORM.get(lbl, lbl), eid) for lbl, eid in entity_pairs]
    # Deduplicate after normalization — NER2 may return both "ProductionPlan" and
    # "ProductionPlanVersion" for the same ID; normalization collapses them to the
    # same label, creating duplicate (label, eid) pairs that inflate entity_count.
    _seen_ep: set[tuple] = set()
    entity_pairs = [ep for ep in entity_pairs if ep not in _seen_ep and not _seen_ep.add(ep)]  # type: ignore[func-returns-value]
    # Drop real-entity pairs where the ID is a pure-alpha word (NER false positive).
    entity_pairs = [(lbl, eid) for lbl, eid in entity_pairs
                    if not eid or re.search(r"[0-9\-]", eid)]

    # Augment entity_pairs with label type hints from NER2 node_labels (no specific ID).
    # Only applied when at least one real entity already exists — prevents aggregate
    # queries (entity_pairs=[]) from being misrouted to plan_query.
    # No primitive gate: entity_count reflects ALL entity types mentioned in the question,
    # not just those with a direct primitive from the anchor. This ensures 3-type queries
    # (e.g. Vehicle + AssemblyShop + ManufacturingPlant) correctly route to Scenario D.
    if entity_pairs:
        _q_lower = rewritten_question.lower()
        existing_labels = {label for label, _ in entity_pairs}
        for label, score in node_labels:
            if score < 0.5 or not label:
                continue
            norm_label = _VERSION_SPEC_NORM.get(label, label)
            if norm_label in existing_labels:
                continue
            # Text-presence guard: only add the type hint when the label appears as a
            # whole word (word-boundary regex) in the rewritten question.
            # This replaces the old prefix guard — the word-boundary match already handles
            # the "Vehicle inside VehicleVariant" case:
            #   \bvehicle\b does NOT match in "vehiclevariant" (no word boundary after 'e')
            #   \bvehicle\b DOES match in "which vehicles are instances of vehiclevariant..."
            # Covers common plural forms: y→ies (VehicleFamily/VehicleFamilies) and +s.
            _ll = norm_label.lower()
            _ll_plural = (
                (_ll[:-1] + "ies") if _ll.endswith("y")
                else (_ll + "es") if _ll.endswith(("s", "sh", "ch", "x", "z"))
                else (_ll + "s")
            )
            _txt_pat = r"\b(?:" + re.escape(_ll) + r"|" + re.escape(_ll_plural) + r")\b"
            if not re.search(_txt_pat, _q_lower):
                continue
            entity_pairs.append((norm_label, ""))
            existing_labels.add(norm_label)

        # ── Direct KG-label scan: catch verbatim CamelCase labels the NER synonym
        # map misses (e.g. "ProductionProcesses" — synonym \bprocesses\b doesn't
        # match inside the compound word; the canonical plural does).
        # ── Direct KG-label scan: catch verbatim CamelCase labels the NER synonym
        # map misses (e.g. "ProductionProcesses" — synonym \bprocesses\b doesn't
        # match inside the compound word; the canonical plural does).
        for _kgl in ner.ALL_NODE_LABELS:
            _knorm = _VERSION_SPEC_NORM.get(_kgl, _kgl)
            if _knorm in existing_labels:
                continue
            _kll  = _knorm.lower()
            _kllp = (
                (_kll[:-1] + "ies") if _kll.endswith("y")
                else (_kll + "es") if _kll.endswith(("s", "sh", "ch", "x", "z"))
                else (_kll + "s")
            )
            _kpat = r"\b(?:" + re.escape(_kll) + r"|" + re.escape(_kllp) + r")\b"
            if re.search(_kpat, _q_lower):
                entity_pairs.append((_knorm, ""))
                existing_labels.add(_knorm)

    entity_count = len(entity_pairs)

    # ── Heuristic status-condition fallback (entity_count=0 + single label) ──
    # The rewriter sometimes misses simple "active/completed/approved X" filters
    # when there's no entity context to resolve. This zero-LLM fallback detects
    # known status adjectives and looks up the correct property name from the schema.
    if not _any_conditions and entity_count == 0:
        _primary_labels = [lbl for lbl, sc in node_labels if sc >= 0.5]
        if len(_primary_labels) == 1:
            _inferred = _infer_status_condition(rewritten_question, _primary_labels[0])
            if _inferred:
                _property_conditions = [_inferred]
                _any_conditions      = True

    # Rebuild ner_result for display: use final normalized+augmented entity_pairs
    # so the context panel shows canonical labels (e.g. "Operation" not "OperationVersion")
    # and type-hint targets (e.g. "Part") alongside instance pairs.
    ner_result = {
        "node_instance_pairs": [
            (lbl, eid, "identifier") for lbl, eid in entity_pairs if eid
        ],
        "node_labels": [(lbl, 1.0) for lbl, eid in entity_pairs if not eid],
        "rewritten_query": rewritten_question,
        "raw_instances": ner_rewritten2.get("raw_instances", []),
    }

    # ── Compound question detection ───────────────────────────────────────────
    # Questions with 2+ "?" or containing "also/as well" are compound — split
    # them into independent sub-tasks before routing so each sub-question gets
    # its own logic op and execution path.
    _compound = bool(
        re.search(r"\b(also|as well)\b", question, re.IGNORECASE)
        or question.count("?") >= 2
    )
    if _compound:
        _raw_parts = [p.strip() for p in question.split("?") if p.strip()]
        _sub_qs    = [p if p.endswith("?") else p + "?" for p in _raw_parts]
        if len(_sub_qs) >= 2:
            _sub_tasks: list[dict] = []
            for _sq in _sub_qs:
                _sq_ner   = ner.extract_entities(_sq)
                _sq_pairs = [
                    (_VERSION_SPEC_NORM.get(l, l), i)
                    for l, i in [
                        (p[0], p[1]) for p in _sq_ner.get("node_instance_pairs", [])
                    ]
                ]
                _sq_real  = [(l, i) for l, i in _sq_pairs if i and re.search(r"[0-9\-]", i)]
                _sq_hints = [l for l, i in _sq_pairs if not i]
                # Add node_labels as type hints when not already present
                for _nlbl, _ in _sq_ner.get("node_labels", []):
                    _nlbl_n = _VERSION_SPEC_NORM.get(_nlbl, _nlbl)
                    if _nlbl_n not in _sq_hints and _nlbl_n not in [l for l, _ in _sq_real]:
                        _sq_hints.append(_nlbl_n)
                _tgt_lbl = _sq_hints[0] if _sq_hints else ""
                _sq_logic: str | None = (
                    "OR"  if (len(_sq_real) >= 2 and re.search(r"\bor\b",  _sq, re.IGNORECASE))
                    else "AND" if len(_sq_real) >= 2
                    else None
                )
                # Pre-build sub_problems so the HITL UI can render the
                # same editable format as complex_decomposition
                _sps: list[dict] = []
                if len(_sq_real) == 1 and len(_sq_hints) >= 2:
                    # Single anchor + multiple type hints → try A→B→C chain
                    _chain_sps = _try_primitive_chain(_sq_real[0][0], _sq_real[0][1], _sq_hints)
                    if _chain_sps:
                        _sps = _chain_sps
                        _sq_logic = "CHAIN"   # sequential — not a set-op
                    elif _tgt_lbl:
                        # Chain failed → fall back to single two_node sub-problem
                        _sps = [{
                            "id":          "sp1",
                            "type":        "two_node",
                            "label_a":     _sq_real[0][0],
                            "id_a":        _sq_real[0][1],
                            "label_b":     _tgt_lbl,
                            "id_b":        "",
                            "description": f"Find {_tgt_lbl} linked to {_sq_real[0][0]} {_sq_real[0][1]}",
                        }]
                elif _sq_real and _tgt_lbl:
                    # Multiple anchors → one sub-problem per anchor (parallel)
                    for _idx, (_al, _ai) in enumerate(_sq_real):
                        _sps.append({
                            "id":          f"sp{_idx + 1}",
                            "type":        "two_node",
                            "label_a":     _al,
                            "id_a":        _ai,
                            "label_b":     _tgt_lbl,
                            "id_b":        "",
                            "description": f"Find {_tgt_lbl} linked to {_al} {_ai}",
                        })
                elif _sq_real and not _tgt_lbl:
                    # Single anchor, no type hint → one_node sub-problem for UI editability
                    _sps = [{
                        "id":          "sp1",
                        "type":        "one_node",
                        "label_a":     _sq_real[0][0],
                        "id_a":        _sq_real[0][1],
                        "description": f"Look up {_sq_real[0][0]} {_sq_real[0][1]}",
                    }]
                elif not _sq_real:
                    # No anchor found → placeholder one_node for UI editability
                    _sps = [{
                        "id":          "sp1",
                        "type":        "one_node",
                        "label_a":     _tgt_lbl,
                        "id_a":        "",
                        "description": f"Look up {_tgt_lbl}" if _tgt_lbl else "Specify entity to look up",
                    }]
                _sub_tasks.append({
                    "question":     _sq,
                    "logic_op":     _sq_logic,
                    "label":        _tgt_lbl,
                    "sub_problems": _sps,
                })

            _split_preview = "\n".join(
                f"{_i + 1}. {_st['question']}"
                for _i, _st in enumerate(_sub_tasks)
            )
            _split_msg = (
                f"I detected {len(_sub_tasks)} sub-questions in your input. "
                f"Review and edit below:\n\n{_split_preview}\n\n"
                f"Click **✓ Confirm** to execute."
            )
            _split_pending = {
                "type":              "question_split",
                "sub_tasks":         _sub_tasks,
                "original_question": question,
            }
            memory_service.set_pending_confirmation(session_state, _split_pending)
            memory_service.append_message(session_state, "user", question)
            memory_service.append_message(session_state, "assistant", _split_msg)
            return _build_result(
                _split_msg, "high_level", question, [],
                "Compound question — awaiting split confirmation.",
                ner_result, memory_service.get_entity_working_set(session_state),
            )

    # ── HITL Gate: condition confirmation ────────────────────────────────────
    # When the rewrite agent extracted temporal or property conditions, pause and
    # ask the user to confirm (and optionally edit) before executing the query.
    if _any_conditions:
        _meta = _request_log_meta(session_state)
        logger.warning(
            f"condition confirmation gate triggered request_id={_meta['request_id']} session_id={_meta['session_id']}",
            extra={
                "stage": "condition_confirmation_gate",
                "question": _clip_for_log(question),
                "rewritten_question": _clip_for_log(rewritten_question),
                "entity_pairs": _clip_for_log(str(entity_pairs)),
                "time_conditions": _clip_for_log(json.dumps(_time_conditions, default=str)),
                "property_conditions": _clip_for_log(json.dumps(_property_conditions, default=str)),
                **_meta,
            },
        )
        pending = {
            "type":                "condition_confirmation",
            "time_conditions":     _time_conditions,
            "property_conditions": _property_conditions,
            "original_question":   question,
            "rewritten_question":  rewritten_question,
            "entity_pairs":        entity_pairs,
            "node_labels":         node_labels,
            "session_id":          session_id,
            "description":         _build_condition_description(
                                       _time_conditions, _property_conditions),
        }
        memory_service.set_pending_confirmation(session_state, pending)
        msg = (
            "I've extracted the following conditions from your query. "
            "Please review and confirm (or edit) them in the panel below:\n\n"
            + pending["description"]
        )
        memory_service.append_message(session_state, "user", question)
        memory_service.append_message(session_state, "assistant", msg)
        return _build_result(
            msg, "specific", rewritten_question, [],
            "condition_confirmation_pending", ner_result,
            memory_service.get_entity_working_set(session_state),
        )

    intent         = "specific"
    tool_calls:  list[dict] = []
    reasoning    = ""
    result_entities: list[dict] = []
    answer       = ""

    # ── Scenario A: 1 entity ──────────────────────────────────────────────────
    if entity_count == 1:
        label, eid = entity_pairs[0]
        answer, tool_calls, result_entities = _execute_single_node_query(
            label, eid, rewritten_question
        )
        reasoning = f"1-entity route: {label}:{eid}"

    # ── Scenario B: 2 entities ────────────────────────────────────────────────
    elif entity_count == 2:
        # If one entity is a type-only target (empty ID), the intent is always
        # RELATIONAL — skip decomposability check and go straight to plan_query.
        decomp_fallback = None
        has_type_hint = any(eid == "" for _, eid in entity_pairs)
        if has_type_hint:
            decomp_intent = "RELATIONAL"
            time_filter   = _normalize_time_filter(rewritten_question)
        else:
            decomp_result = _check_decomposability(rewritten_question, entity_pairs)
            decomp_intent = decomp_result["decomposability"]
            time_filter   = decomp_result["time_filter"]
            decomp_fallback = decomp_result.get("fallback_reason")

        if decomp_intent == "INDEPENDENT":
            # HITL gate: confirm with user before executing two separate lookups.
            parts_desc = [
                f"{lbl} '{eid}'" if eid else f"{lbl} (any)"
                for lbl, eid in entity_pairs
            ]
            indep_description = (
                "I'll look up each entity independently:\n"
                + "\n".join(f"  - {d}" for d in parts_desc)
            )
            _indep_pending = {
                "type":               "independent_decomposition",
                "description":        indep_description,
                "entity_pairs":       entity_pairs,
                "original_question":  question,
                "rewritten_question": rewritten_question,
                "decomp_fallback":    decomp_fallback,
            }
            memory_service.set_pending_confirmation(session_state, _indep_pending)
            gate_msg = (
                "This question appears to ask about two independent entities. "
                "I'll look them up separately:\n\n"
                f"> {indep_description}\n\n"
                "Click **\u2713 Confirm** to execute, or **\u2717 Reject** to rephrase."
            )
            memory_service.append_message(session_state, "user", question)
            memory_service.append_message(session_state, "assistant", gate_msg)
            return _build_result(
                gate_msg, "specific", rewritten_question, [],
                "HITL: 2-entity INDEPENDENT pending confirmation.",
                ner_result, memory_service.get_entity_working_set(session_state),
            )

        else:  # RELATIONAL — execute directly, no HITL
            answer, tool_calls, result_entities, intent, reasoning = _execute_relational_query(
                entity_pairs, question, rewritten_question,
                time_filter, decomp_fallback,
                clicked_entity, working_set,
                session_state, session_id, max_tool_rounds,
            )

    # ── Scenario D: 3+ entities — decompose + HITL Gate 2 ────────────────────
    elif entity_count >= 3:
        _real_anchors  = [(l, i) for l, i in entity_pairs if i]
        _type_hints    = [l for l, i in entity_pairs if not i]

        # ── Multi-anchor AND/OR plan: ≥2 real anchors + exactly 1 type-hint, all with
        # direct primitives to that target → build a flat AND/OR sub-problem list so
        # _execute_decomposition's AND/OR block can intersect/union cleanly.
        # (Compound "also/as well" questions are intercepted before routing and never
        # reach here — see compound detection block above.)
        _and_sps = None
        if len(_real_anchors) >= 2 and len(_type_hints) == 1:
            _tgt_lbl = _type_hints[0]
            _cand_sps: list[dict] = []
            for _al, _ai in _real_anchors:
                _p = lookup_primitive(_al, _ai, _tgt_lbl, "")
                if _p and _p["params"].get("a_id") == _ai:
                    _cand_sps.append({
                        "id":          f"sp{len(_cand_sps) + 1}",
                        "type":        "two_node",
                        "label_a":     _al,
                        "id_a":        _ai,
                        "label_b":     _tgt_lbl,
                        "id_b":        "",
                        "description": f"Find {_tgt_lbl} linked to {_al} {_ai}",
                    })
            if len(_cand_sps) == len(_real_anchors):   # every anchor matched
                _and_sps = _cand_sps

        if _and_sps:
            # Detect OR vs AND from the rewritten question text
            _logic_op = (
                "OR" if re.search(r"\bor\b", rewritten_question, re.IGNORECASE)
                else "AND"
            )
            _qualifier   = "ANY" if _logic_op == "OR" else "ALL"
            _anchor_desc = f" {_logic_op} ".join(f"{al} {ai}" for al, ai in _real_anchors)
            decomp = {
                "description":  (
                    f"Find {_type_hints[0]}(s) connected to {_qualifier} of: {_anchor_desc}"
                ),
                "sub_problems": _and_sps,
                "logic_tree":   {"op": _logic_op},
                "pivot_entity": _type_hints[0],
            }
        else:
            # ── Try deterministic primitive chain first (avoids LLM schema hallucination)
            # Conditions: exactly 1 real anchor + N type-hint labels + all connected by primitives
            _prim_chain = None
            if len(_real_anchors) == 1 and _type_hints:
                _anc_lbl, _anc_id = _real_anchors[0]
                _prim_chain = _try_primitive_chain(_anc_lbl, _anc_id, _type_hints)

            if _prim_chain:
                _chain_desc = (
                    f"{_real_anchors[0][0]} {_real_anchors[0][1]}"
                    + "".join(f" → {sp['label_b']}" for sp in _prim_chain)
                )
                decomp = {
                    "description":  f"Chain query: {_chain_desc}",
                    "sub_problems": _prim_chain,
                    "logic_tree":   {"op": "CHAIN"},
                    "pivot_entity": _prim_chain[-1]["label_b"] if _prim_chain else "",
                }
            else:
                decomp = _decompose_to_primitives(rewritten_question, entity_pairs)
                # Structural check: if the LLM says CHAIN but the sub-problems are
                # not actually a chain (each sp's label_b ≠ next sp's label_a), the
                # LLM was confused — override to INDEPENDENT so both the UI label and
                # execution are correct.
                _sps_out = decomp.get("sub_problems", [])
                _is_actual_chain = (
                    len(_sps_out) > 1
                    and all(
                        _sps_out[_i].get("label_b") == _sps_out[_i + 1].get("label_a")
                        for _i in range(len(_sps_out) - 1)
                    )
                )
                if decomp.get("logic_tree", {}).get("op") == "CHAIN" and not _is_actual_chain:
                    decomp["logic_tree"] = {"op": "INDEPENDENT"}

        pending = {
            "type":               "complex_decomposition",
            "description":        decomp.get("description", ""),
            "sub_problems":       decomp.get("sub_problems", []),
            "logic_tree":         decomp.get("logic_tree", {}),
            "pivot_entity":       decomp.get("pivot_entity", ""),
            "original_question":  question,
            "rewritten_question": rewritten_question,
            "entity_pairs":       entity_pairs,
        }
        memory_service.set_pending_confirmation(session_state, pending)
        description = decomp.get("description", "")
        gate2_msg = (
            f"I've decomposed your question into a multi-step query plan:\n\n"
            f"> {description}\n\n"
            f"Click **✓ Confirm** to execute, or **✗ Reject** to rephrase."
        )
        memory_service.append_message(session_state, "user", question)
        memory_service.append_message(session_state, "assistant", gate2_msg)
        return _build_result(
            gate2_msg, "high_level", rewritten_question, [],
            "HITL Gate 2: 3+ entity decomposition pending.",
            ner_result, memory_service.get_entity_working_set(session_state),
        )

    else:
        # entity_count == 0: no specific IDs but question is self-contained
        # (e.g. aggregate/date queries like "how many vehicles on 2015-10-01?").
        # Build label-only pairs from NER for schema injection, then tool loop.
        label_pairs = [
            (label, "")
            for label, score in node_labels
            if score >= 0.5
        ]
        answer, tool_calls, result_entities, intent, reasoning = _run_tool_loop(
            question, rewritten_question,
            clicked_entity, working_set, label_pairs,
            session_state, session_id, max_tool_rounds,
        )

    # ── Update entity working set ──────────────────────────────────────────────
    _clicked     = context_manager.get_clicked_entity()
    _clicked_key = (
        (_clicked.get("type", ""), _clicked.get("identifier", ""))
        if _clicked else ("", "")
    )
    new_entities: list[dict] = []
    for label, val, attr in ner_pairs:
        if label != "Unknown":
            norm_label = _VERSION_SPEC_NORM.get(label, label)
            new_entities.append({
                "label":       norm_label,
                "id":          val,
                "description": f"{attr}:{val}",
                "source":      "ner",
                "ttl":         memory_service.TTL_NER,
            })
    for e in result_entities:
        if (e["label"], e["id"]) != _clicked_key:
            new_entities.append(e)
    memory_service.upsert_entities(session_state, new_entities)

    # ── Persist conversation & interaction ────────────────────────────────────
    wset_after = memory_service.get_entity_working_set(session_state)
    _meta = {
        "rewritten_question": rewritten_question,
        "ner_context":        ner_result,
        "tool_calls_made":    tool_calls,
        "reasoning":          reasoning,
        "working_set":        wset_after,
        "intent":             intent,
    }
    memory_service.append_message(session_state, "user", question)
    memory_service.append_message(session_state, "assistant", answer, metadata=_meta)
    memory_service.record_interaction(
        session_id=session_id,
        event_type="ASK_QUESTION",
        entity_type=clicked_entity.get("type", "") if clicked_entity else "",
        entity_id=clicked_entity.get("identifier", "") if clicked_entity else "",
        content=question,
        resolved_intent=intent,
    )

    return _build_result(answer, intent, rewritten_question, tool_calls, reasoning,
                         ner_result, wset_after)
