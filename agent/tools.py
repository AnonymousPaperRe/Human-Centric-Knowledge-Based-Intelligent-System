"""
Agent Tools — OpenAI function calling tool definitions and dispatch.
Each tool maps to a service method call.
"""
import json
from services import neo4j_service, template_service, schema_service
from services.neo4j_service import run_cypher


def is_safe_read_only_cypher(query: str) -> bool:
    q = query.lower()
    blocked = ["create ", "merge ", "delete ", "set ", "remove ", "call "]
    return not any(tok in q for tok in blocked)


# ── Tool definitions for OpenAI ──────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "execute_cypher",
            "description": (
                "Execute a Cypher query against the Neo4j knowledge graph. "
                "Use for specific data retrieval when you know the exact query needed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The Cypher query to execute."},
                    "params": {
                        "type": "object",
                        "description": "Query parameters as key-value pairs.",
                        "additionalProperties": True,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "use_template",
            "description": (
                "Use a stored retrieval template by name with parameter values. "
                "Built-in templates include: vehicles_by_plan(plan_id), "
                "tasks_by_process(process_id), personnel_by_process(process_id), "
                "tools_by_task(task_id), equipment_by_task(task_id), "
                "parts_by_task(task_id), orders_by_plan(plan_id), "
                "plans_for_variant(variant_id), vehicle_count_by_plan(plan_id), "
                "task_count_by_process(process_id), "
                "resource_summary_by_process(process_id)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "template_name": {
                        "type": "string",
                        "description": "Name of the stored RetrievalTemplate.",
                    },
                    "params": {
                        "type": "object",
                        "description": "Parameter values to inject into the template.",
                        "additionalProperties": True,
                    },
                },
                "required": ["template_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_entity_details",
            "description": "Get all properties and relationships of a specific entity by type and identifier.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "description": "The node label/type (e.g. PartSpec, Vehicle, ChangeSet).",
                    },
                    "identifier": {
                        "type": "string",
                        "description": "The unique identifier of the entity.",
                    },
                },
                "required": ["entity_type", "identifier"],
            },
        },
    },
    # {
    #     "type": "function",
    #     "function": {
    #         "name": "analyze_change_impact",
    #         "description": (
    #             "Traverse the digital thread to get the full impact cascade of a ChangeSet. "
    #             "Returns all affected specifications, processes, vehicles, and inventory."
    #         ),
    #         "parameters": {
    #             "type": "object",
    #             "properties": {
    #                 "change_set_id": {
    #                     "type": "string",
    #                     "description": "Identifier of the ChangeSet to analyze.",
    #                 }
    #             },
    #             "required": ["change_set_id"],
    #         },
    #     },
    # },
    # {
    #     "type": "function",
    #     "function": {
    #         "name": "aggregate_production_metrics",
    #         "description": (
    #             "Get aggregated production metrics for high-level analysis: "
    #             "counts, rates, status distributions. Use for broad analytical questions."
    #         ),
    #         "parameters": {
    #             "type": "object",
    #             "properties": {
    #                 "time_range": {
    #                     "type": "string",
    #                     "enum": ["today", "week", "month"],
    #                     "description": "Time window for aggregation.",
    #                 },
    #                 "shop_id": {
    #                     "type": "string",
    #                     "description": "Optional: filter by ProductionShop identifier.",
    #                 },
    #             },
    #             "required": ["time_range"],
    #         },
    #     },
    # },
    {
        "type": "function",
        "function": {
            "name": "get_schema_info",
            "description": "Get the current KG schema — node types, properties, relationship types.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_type": {
                        "type": "string",
                        "description": "Optional: filter schema info to a specific node type.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plan_and_query",
            "description": (
                "PREFERRED over execute_cypher for two-entity relationship queries. "
                "Builds a deterministic Cypher query from two node labels using a verified "
                "schema registry — no hallucinated relationship names. "
                "The primitive key is built as '{label_a}_to_{label_b}' (both orderings tried). "
                "Use this whenever you know two entity labels, e.g. Vehicle+WorkStep, Vehicle+Part."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "label_a": {
                        "type": "string",
                        "description": "First entity label (e.g. 'Vehicle', 'Operation').",
                    },
                    "id_a": {
                        "type": "string",
                        "description": "Identifier of the first entity.",
                    },
                    "label_b": {
                        "type": "string",
                        "description": "Second entity label (e.g. 'WorkStep', 'PartBatch', 'Personnel').",
                    },
                    "id_b": {
                        "type": "string",
                        "description": "Identifier of the second entity (if known; omit if unknown).",
                    },
                },
                "required": ["label_a", "id_a", "label_b"],
            },
        },
    },
]


# ── Tool dispatch ────────────────────────────────────────────────────────────

def dispatch(tool_name: str, tool_args: dict) -> str:
    """Dispatch a tool call to the appropriate service. Returns JSON string."""
    try:
        if tool_name == "execute_cypher":
            result = neo4j_service.safe_run(
                tool_args.get("query", ""),
                tool_args.get("params", {}),
            )

        elif tool_name == "use_template":
            result = template_service.execute_template(
                tool_args.get("template_name", ""),
                tool_args.get("params", {}),
            )

        elif tool_name == "get_entity_details":
            entity_type = tool_args.get("entity_type", "")
            identifier = tool_args.get("identifier", "")
            rows = run_cypher(
                f"MATCH (n:{entity_type} {{identifier: $id}}) "
                "OPTIONAL MATCH (n)-[:CURRENT_SPECIFICATION]->(spec) "
                "OPTIONAL MATCH (n)-[:CURRENT_VERSION]->(ver) "
                "RETURN properties(n) AS props, "
                "[(n)-[r]->(m) | {rel_type: type(r), target_id: m.identifier, target_label: labels(m)[0]}] AS rels, "
                "properties(spec) AS spec_props, labels(spec)[0] AS spec_label, "
                "properties(ver) AS version_props, labels(ver)[0] AS version_label",
                {"id": identifier},
            )
            result = {"ok": True, "data": rows, "error": None}

        # elif tool_name == "analyze_change_impact":
        #     cs_id = tool_args.get("change_set_id", "")
        #     rows = run_cypher(
        #         "MATCH (cs:ChangeSet {identifier: $cs_id})-[:HAS_ACTION]->(ca:ChangeAction) "
        #         "OPTIONAL MATCH (ca)-[:AFFECTS_OLD]->(old_s:Specification) "
        #         "OPTIONAL MATCH (ca)-[:AFFECTS_NEW]->(new_s:Specification) "
        #         "OPTIONAL MATCH (ca)-[:IMPACTS_SPECIFICATION]->(imp_s:Specification) "
        #         "OPTIONAL MATCH (ca)-[:IMPACTS_PROCESS]->(pp:ProductionProcess) "
        #         "OPTIONAL MATCH (ca)-[:IMPACTS_VEHICLE]->(v:Vehicle) "
        #         "RETURN ca.identifier AS action_id, ca.actionType AS action_type, "
        #         "ca.reason AS reason, "
        #         "old_s.identifier AS old_spec, new_s.identifier AS new_spec, "
        #         "collect(DISTINCT imp_s.identifier) AS impacted_specs, "
        #         "collect(DISTINCT pp.identifier) AS impacted_processes, "
        #         "collect(DISTINCT v.identifier) AS impacted_vehicles",
        #         {"cs_id": cs_id},
        #     )
        #     result = {"ok": True, "data": rows, "error": None}

        # elif tool_name == "aggregate_production_metrics":
        #     time_range = tool_args.get("time_range", "today")
        #     shop_id = tool_args.get("shop_id")

        #     time_filter = {
        #         "today": "date() = date(pp.createTime)",
        #         "week": "date() - duration('P7D') <= date(pp.createTime)",
        #         "month": "date() - duration('P30D') <= date(pp.createTime)",
        #     }.get(time_range, "true")

        #     shop_clause = ""
        #     shop_params = {}
        #     if shop_id:
        #         shop_clause = "AND EXISTS { (pp)-[:occursAt]->(:ProductionShop {identifier: $shop_id}) }"
        #         shop_params = {"shop_id": shop_id}

        #     rows = run_cypher(
        #         f"MATCH (pp:ProductionProcess) "
        #         f"WHERE {time_filter} {shop_clause} "
        #         "OPTIONAL MATCH (pp)-[:producesVehicle]->(v:Vehicle) "
        #         "OPTIONAL MATCH (pp)-[:hasState]->(pps:ProductionProcessState) "
        #         "RETURN count(DISTINCT pp) AS process_count, "
        #         "count(DISTINCT v) AS vehicle_count, "
        #         "collect(DISTINCT pps.status) AS status_values",
        #         shop_params,
        #     )
        #     result = {"ok": True, "data": rows, "error": None}

        elif tool_name == "get_schema_info":
            node_type = tool_args.get("node_type")
            if node_type:
                data = schema_service.get_schema_node(node_type)
                result = {"ok": True, "data": data or {}, "error": None}
            else:
                tree = schema_service.get_schema_tree()
                # Also fetch domain node types from the actual graph
                label_rows = run_cypher(
                    "CALL db.labels() YIELD label RETURN label ORDER BY label"
                )
                result = {
                    "ok": True,
                    "data": {"schema_tree": tree, "all_labels": label_rows},
                    "error": None,
                }
        elif tool_name == "plan_and_query":
            from agent.query_planner import plan_query
            pairs = [(tool_args["label_a"], tool_args["id_a"])]
            if tool_args.get("label_b"):
                pairs.append((tool_args["label_b"], tool_args.get("id_b", "")))
            result = plan_query(pairs)

        else:
            result = {"ok": False, "data": [], "error": f"Unknown tool: {tool_name}"}

        return json.dumps(result, default=str)

    except Exception as exc:
        return json.dumps({"ok": False, "data": [], "error": str(exc)})
