"""
Template Service — CRUD and execution of parameterized Cypher query templates
stored as RetrievalTemplate nodes in Neo4j.
"""
import json
from datetime import datetime
from services.neo4j_service import run_cypher


BUILTIN_TEMPLATES: dict[str, dict] = {
    "vehicles_by_plan": {
        "name": "vehicles_by_plan",
        "description": "List vehicles produced by production processes realizing a production plan version.",
        "cypher": (
            "MATCH (ppv:ProductionPlanVersion {identifier: $plan_id}) "
            "<-[:REALIZES_PLAN]-(proc:ProductionProcess)-[:PRODUCES_VEHICLE]->(v:Vehicle) "
            "OPTIONAL MATCH (v)-[:INSTANCE_OF]->(variant:VehicleVariant) "
            "RETURN ppv.identifier AS plan_id, proc.identifier AS process_id, "
            "v.identifier AS vehicle_id, v.name AS vehicle_name, "
            "variant.identifier AS variant_id "
            "ORDER BY process_id, vehicle_id"
        ),
        "params": ["plan_id"],
        "category": "builtin",
        "created_at": "builtin",
    },
    "tasks_by_process": {
        "name": "tasks_by_process",
        "description": "List operational tasks belonging to a production process.",
        "cypher": (
            "MATCH (proc:ProductionProcess {identifier: $process_id})-[:HAS_TASK]->(task:OperationalTask) "
            "OPTIONAL MATCH (task)-[:INSTANTIATES_OPERATION]->(opv:OperationVersion) "
            "RETURN proc.identifier AS process_id, task.identifier AS task_id, "
            "opv.identifier AS operation_version_id, opv.name AS operation_name "
            "ORDER BY task_id"
        ),
        "params": ["process_id"],
        "category": "builtin",
        "created_at": "builtin",
    },
    "personnel_by_process": {
        "name": "personnel_by_process",
        "description": "List personnel assigned to tasks within a production process.",
        "cypher": (
            "MATCH (proc:ProductionProcess {identifier: $process_id})-[:HAS_TASK]->(task:OperationalTask) "
            "-[:HAS_PARTICIPANT]->(p:Personnel) "
            "RETURN DISTINCT proc.identifier AS process_id, task.identifier AS task_id, "
            "p.identifier AS personnel_id, p.name AS personnel_name "
            "ORDER BY task_id, personnel_id"
        ),
        "params": ["process_id"],
        "category": "builtin",
        "created_at": "builtin",
    },
    "tools_by_task": {
        "name": "tools_by_task",
        "description": "List tool instances used by an operational task, including role/spec when present.",
        "cypher": (
            "MATCH (task:OperationalTask {identifier: $task_id})-[:USE_TOOL]->(tool:ToolInstance) "
            "OPTIONAL MATCH (tool)-[:INSTANCE_OF]->(tool_role) "
            "OPTIONAL MATCH (tool)-[:CONFIGURED_TO]->(tool_spec) "
            "RETURN task.identifier AS task_id, tool.identifier AS tool_id, "
            "tool_role.identifier AS tool_role_id, labels(tool_role)[0] AS tool_role_label, "
            "tool_spec.identifier AS tool_spec_id, labels(tool_spec)[0] AS tool_spec_label "
            "ORDER BY tool_id"
        ),
        "params": ["task_id"],
        "category": "builtin",
        "created_at": "builtin",
    },
    "equipment_by_task": {
        "name": "equipment_by_task",
        "description": "List equipment instances used by an operational task, including role/spec when present.",
        "cypher": (
            "MATCH (task:OperationalTask {identifier: $task_id})-[:USE_EQUIPMENT]->(eq:EquipmentInstance) "
            "OPTIONAL MATCH (eq)-[:INSTANCE_OF]->(eq_role) "
            "OPTIONAL MATCH (eq)-[:CONFIGURED_TO]->(eq_spec) "
            "RETURN task.identifier AS task_id, eq.identifier AS equipment_id, eq.name AS equipment_name, "
            "eq_role.identifier AS equipment_role_id, labels(eq_role)[0] AS equipment_role_label, "
            "eq_spec.identifier AS equipment_spec_id, labels(eq_spec)[0] AS equipment_spec_label "
            "ORDER BY equipment_id"
        ),
        "params": ["task_id"],
        "category": "builtin",
        "created_at": "builtin",
    },
    "parts_by_task": {
        "name": "parts_by_task",
        "description": "List part instances consumed by an operational task.",
        "cypher": (
            "MATCH (task:OperationalTask {identifier: $task_id})-[:CONSUMES_PART]->(part:PartInstance) "
            "OPTIONAL MATCH (part)-[:INSTANCE_OF]->(part_role:Part) "
            "OPTIONAL MATCH (part)-[:CONFIGURED_TO]->(part_spec:PartSpecification) "
            "RETURN task.identifier AS task_id, part.identifier AS part_instance_id, part.name AS part_name, "
            "part_role.identifier AS part_role_id, part_spec.identifier AS part_spec_id "
            "ORDER BY part_instance_id"
        ),
        "params": ["task_id"],
        "category": "builtin",
        "created_at": "builtin",
    },
    "orders_by_plan": {
        "name": "orders_by_plan",
        "description": "List production order versions instantiating a production plan version.",
        "cypher": (
            "MATCH (pov:ProductionOrderVersion)-[:INSTANTIATES_PLAN]->(ppv:ProductionPlanVersion {identifier: $plan_id}) "
            "RETURN pov.identifier AS order_version_id, ppv.identifier AS plan_id "
            "ORDER BY order_version_id"
        ),
        "params": ["plan_id"],
        "category": "builtin",
        "created_at": "builtin",
    },
    "plans_for_variant": {
        "name": "plans_for_variant",
        "description": "List production plan versions and planned quantity for a vehicle variant specification.",
        "cypher": (
            "MATCH (ppv:ProductionPlanVersion)-[r:PLANS_VARIANT]->"
            "(variant:VehicleVariantSpecification {identifier: $variant_id}) "
            "RETURN ppv.identifier AS plan_id, variant.identifier AS variant_id, "
            "r.quantity AS planned_quantity "
            "ORDER BY plan_id"
        ),
        "params": ["variant_id"],
        "category": "builtin",
        "created_at": "builtin",
    },
    "vehicle_count_by_plan": {
        "name": "vehicle_count_by_plan",
        "description": "Count vehicles produced for a production plan version.",
        "cypher": (
            "MATCH (ppv:ProductionPlanVersion {identifier: $plan_id}) "
            "<-[:REALIZES_PLAN]-(proc:ProductionProcess)-[:PRODUCES_VEHICLE]->(v:Vehicle) "
            "RETURN ppv.identifier AS plan_id, count(DISTINCT v) AS vehicle_count"
        ),
        "params": ["plan_id"],
        "category": "builtin_analytic",
        "created_at": "builtin",
    },
    "task_count_by_process": {
        "name": "task_count_by_process",
        "description": "Count operational tasks under a production process.",
        "cypher": (
            "MATCH (proc:ProductionProcess {identifier: $process_id})-[:HAS_TASK]->(task:OperationalTask) "
            "RETURN proc.identifier AS process_id, count(DISTINCT task) AS task_count"
        ),
        "params": ["process_id"],
        "category": "builtin_analytic",
        "created_at": "builtin",
    },
    "resource_summary_by_process": {
        "name": "resource_summary_by_process",
        "description": "Return distinct counts of tasks, personnel, tools, equipment, and parts for a process.",
        "cypher": (
            "MATCH (proc:ProductionProcess {identifier: $process_id})-[:HAS_TASK]->(task:OperationalTask) "
            "OPTIONAL MATCH (task)-[:HAS_PARTICIPANT]->(p:Personnel) "
            "OPTIONAL MATCH (task)-[:USE_TOOL]->(tool:ToolInstance) "
            "OPTIONAL MATCH (task)-[:USE_EQUIPMENT]->(eq:EquipmentInstance) "
            "OPTIONAL MATCH (task)-[:CONSUMES_PART]->(part:PartInstance) "
            "RETURN proc.identifier AS process_id, "
            "count(DISTINCT task) AS task_count, "
            "count(DISTINCT p) AS personnel_count, "
            "count(DISTINCT tool) AS tool_count, "
            "count(DISTINCT eq) AS equipment_count, "
            "count(DISTINCT part) AS part_count"
        ),
        "params": ["process_id"],
        "category": "builtin_analytic",
        "created_at": "builtin",
    },
}


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def create_template(
    name: str,
    description: str,
    cypher_template: str,
    param_names: list[str],
    category: str = "general",
) -> dict:
    """Create a RetrievalTemplate node in Neo4j."""
    run_cypher(
        "MERGE (t:RetrievalTemplate {name: $name}) "
        "SET t.description = $desc, t.cypherTemplate = $cypher, "
        "t.paramNames = $params, t.category = $cat, t.createdAt = $now",
        {
            "name": name,
            "desc": description,
            "cypher": cypher_template,
            "params": json.dumps(param_names),
            "cat": category,
            "now": _now_str(),
        },
    )
    return get_template(name)


def list_templates() -> list[dict]:
    """Return all RetrievalTemplate nodes."""
    rows = run_cypher(
        "MATCH (t:RetrievalTemplate) "
        "RETURN t.name AS name, t.description AS description, "
        "t.cypherTemplate AS cypher, t.paramNames AS params, "
        "t.category AS category, t.createdAt AS created_at "
        "ORDER BY t.category, t.name"
    )
    for row in rows:
        if row.get("params"):
            try:
                row["params"] = json.loads(row["params"])
            except Exception:
                row["params"] = []
    existing = {row["name"] for row in rows}
    for name, tpl in BUILTIN_TEMPLATES.items():
        if name not in existing:
            rows.append(dict(tpl))
    rows.sort(key=lambda row: ((row.get("category") or ""), row.get("name") or ""))
    return rows


def get_template(name: str) -> dict | None:
    """Return a single template by name, or None if not found."""
    rows = run_cypher(
        "MATCH (t:RetrievalTemplate {name: $name}) "
        "RETURN t.name AS name, t.description AS description, "
        "t.cypherTemplate AS cypher, t.paramNames AS params, "
        "t.category AS category, t.createdAt AS created_at",
        {"name": name},
    )
    if not rows:
        builtin = BUILTIN_TEMPLATES.get(name)
        return dict(builtin) if builtin else None
    row = rows[0]
    if row.get("params"):
        try:
            row["params"] = json.loads(row["params"])
        except Exception:
            row["params"] = []
    return row


def _coerce(value: str):
    """
    Coerce a raw string param value from the UI into the right Python type:
    - Strip surrounding single or double quotes  →  'active' / "active"  →  active
    - Convert pure integers                       →  "2"                  →  2
    - Convert pure floats                         →  "3.14"              →  3.14
    - Everything else stays as a plain string
    """
    v = value.strip()
    # Strip matching surrounding quotes
    if (v.startswith("'") and v.endswith("'")) or \
       (v.startswith('"') and v.endswith('"')):
        v = v[1:-1]
    # Try numeric coercion
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


def execute_template(name: str, param_values: dict) -> dict:
    """
    Execute a stored template by substituting parameters.
    Parameters are passed as a dict to db.cypher_query — no string formatting,
    which prevents injection.
    """
    template = get_template(name)
    if template is None:
        return {"ok": False, "data": [], "error": f"Template '{name}' not found."}

    cypher = template["cypher"]
    expected_params = template.get("params", [])

    # Validate that all expected params are provided
    missing = [p for p in expected_params if p not in param_values]
    if missing:
        return {
            "ok": False,
            "data": [],
            "error": f"Missing parameters: {missing}",
        }

    # Coerce all string values from the UI into correct Python types
    coerced = {k: _coerce(v) if isinstance(v, str) else v
               for k, v in param_values.items()}

    try:
        data = run_cypher(cypher, coerced)
        return {"ok": True, "data": data, "error": None}
    except Exception as exc:
        return {"ok": False, "data": [], "error": str(exc)}


def delete_template(name: str) -> bool:
    """Delete a RetrievalTemplate node. Returns True if deleted."""
    run_cypher(
        "MATCH (t:RetrievalTemplate {name: $name}) DETACH DELETE t",
        {"name": name},
    )
    return get_template(name) is None


def update_template(
    name: str,
    description: str = None,
    cypher_template: str = None,
    param_names: list[str] = None,
    category: str = None,
) -> dict | None:
    """Update fields of an existing template."""
    existing = get_template(name)
    if existing is None:
        return None
    desc = description if description is not None else existing["description"]
    cypher = cypher_template if cypher_template is not None else existing["cypher"]
    params = param_names if param_names is not None else existing.get("params", [])
    cat = category if category is not None else existing.get("category", "general")
    run_cypher(
        "MATCH (t:RetrievalTemplate {name: $name}) "
        "SET t.description = $desc, t.cypherTemplate = $cypher, "
        "t.paramNames = $params, t.category = $cat",
        {
            "name": name,
            "desc": desc,
            "cypher": cypher,
            "params": json.dumps(params),
            "cat": cat,
        },
    )
    return get_template(name)
