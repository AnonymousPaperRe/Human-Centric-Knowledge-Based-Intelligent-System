"""
Schema Service — meta-graph schema registry CRUD.
Enforces immutability of Specification and State parent classes.
Creates ChangeSet records for every schema change (unified digital thread).
"""
from datetime import datetime
from services.neo4j_service import run_cypher


IMMUTABLE_PARENTS = {"Specification", "State", "StructuredNode"}


class ImmutableSchemaError(Exception):
    pass


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _record_schema_change(action: str, node_name: str, reason: str = "") -> str:
    """Create a ChangeSet + ChangeAction for a schema modification."""
    now = _now_str()
    cs_id = f"CS-SCHEMA-{node_name}-{now.replace(' ', 'T').replace(':', '')}"
    ca_id = f"CA-SCHEMA-{node_name}-{now.replace(' ', 'T').replace(':', '')}"

    run_cypher(
        "MERGE (cs:ChangeSet {identifier: $cs_id}) "
        "SET cs.title = $title, cs.changeType = 'SCHEMA', "
        "cs.status = 'IMPLEMENTED', cs.requestTime = $now",
        {
            "cs_id": cs_id,
            "title": f"Schema {action}: {node_name}",
            "now": now,
        },
    )
    run_cypher(
        "MERGE (ca:ChangeAction {identifier: $ca_id}) "
        "SET ca.actionType = $action, ca.reason = $reason, "
        "ca.status = 'DONE', ca.createTime = $now",
        {"ca_id": ca_id, "action": action, "reason": reason, "now": now},
    )
    run_cypher(
        "MATCH (cs:ChangeSet {identifier: $cs_id}), (ca:ChangeAction {identifier: $ca_id}) "
        "MERGE (cs)-[:HAS_ACTION]->(ca)",
        {"cs_id": cs_id, "ca_id": ca_id},
    )
    return cs_id


def create_child_schema(
    base_class: str,
    name: str,
    properties: list[dict],
    relationships: list[dict] | None = None,
    layer: str = "newDigitalThreadLayer.py",
) -> dict:
    """
    Register a new child schema node.
    base_class must be 'Specification' or 'State'.
    properties: [{"name": str, "dataType": str, "required": bool, "defaultValue": str}]
    relationships: [{"name": str, "relationshipType": str, "toNodeName": str, "cardinality": str}]
    """
    if base_class not in ("Specification", "State"):
        raise ValueError(f"base_class must be 'Specification' or 'State', got '{base_class}'")
    if name in IMMUTABLE_PARENTS:
        raise ImmutableSchemaError(f"'{name}' is an immutable parent class and cannot be redefined.")

    now = _now_str()
    # Create SchemaNode
    run_cypher(
        "MERGE (sn:SchemaNode {name: $name}) "
        "SET sn.baseClass = $base, sn.layer = $layer, "
        "sn.isAbstract = false, sn.version = '1.0', sn.createdAt = $now",
        {"name": name, "base": base_class, "layer": layer, "now": now},
    )

    # Create SchemaProperty nodes and link
    for prop in (properties or []):
        prop_node_id = f"{name}__{prop['name']}"
        run_cypher(
            "MERGE (sp:SchemaProperty {name: $prop_node_id}) "
            "SET sp.propertyName = $pname, sp.dataType = $dtype, "
            "sp.required = $req, sp.defaultValue = $dval",
            {
                "prop_node_id": prop_node_id,
                "pname": prop.get("name", ""),
                "dtype": prop.get("dataType", "string"),
                "req": prop.get("required", False),
                "dval": prop.get("defaultValue", ""),
            },
        )
        run_cypher(
            "MATCH (sn:SchemaNode {name: $sname}), (sp:SchemaProperty {name: $prop_node_id}) "
            "MERGE (sn)-[:HAS_PROPERTY]->(sp)",
            {"sname": name, "prop_node_id": prop_node_id},
        )

    # Create SchemaRelationship nodes and link
    for rel in (relationships or []):
        rel_node_id = f"{name}__rel__{rel['name']}"
        run_cypher(
            "MERGE (sr:SchemaRelationship {name: $rel_node_id}) "
            "SET sr.relName = $rname, sr.relationshipType = $rtype, "
            "sr.toNodeName = $to_node, sr.cardinality = $card",
            {
                "rel_node_id": rel_node_id,
                "rname": rel.get("name", ""),
                "rtype": rel.get("relationshipType", ""),
                "to_node": rel.get("toNodeName", ""),
                "card": rel.get("cardinality", "ONE_TO_MANY"),
            },
        )
        run_cypher(
            "MATCH (sn:SchemaNode {name: $sname}), (sr:SchemaRelationship {name: $rel_node_id}) "
            "MERGE (sn)-[:HAS_RELATIONSHIP]->(sr)",
            {"sname": name, "rel_node_id": rel_node_id},
        )

    _record_schema_change("CREATE", name, f"New {base_class} child: {name}")
    return get_schema_node(name)


def update_child_schema(
    name: str,
    properties: list[dict] | None = None,
    relationships: list[dict] | None = None,
) -> dict:
    """Update an existing child schema. Immutable parents are rejected."""
    if name in IMMUTABLE_PARENTS:
        raise ImmutableSchemaError(f"'{name}' is immutable and cannot be modified.")

    existing = get_schema_node(name)
    if existing is None:
        raise ValueError(f"SchemaNode '{name}' not found.")

    now = _now_str()
    # Bump version
    old_version = existing.get("version", "1.0")
    try:
        parts = old_version.split(".")
        new_version = f"{parts[0]}.{int(parts[1]) + 1}" if len(parts) > 1 else str(int(old_version) + 1)
    except Exception:
        new_version = old_version + ".1"

    run_cypher(
        "MATCH (sn:SchemaNode {name: $name}) SET sn.version = $ver",
        {"name": name, "ver": new_version},
    )

    if properties:
        for prop in properties:
            prop_node_id = f"{name}__{prop['name']}"
            run_cypher(
                "MERGE (sp:SchemaProperty {name: $prop_node_id}) "
                "SET sp.propertyName = $pname, sp.dataType = $dtype, "
                "sp.required = $req, sp.defaultValue = $dval",
                {
                    "prop_node_id": prop_node_id,
                    "pname": prop.get("name", ""),
                    "dtype": prop.get("dataType", "string"),
                    "req": prop.get("required", False),
                    "dval": prop.get("defaultValue", ""),
                },
            )
            run_cypher(
                "MATCH (sn:SchemaNode {name: $sname}), (sp:SchemaProperty {name: $prop_node_id}) "
                "MERGE (sn)-[:HAS_PROPERTY]->(sp)",
                {"sname": name, "prop_node_id": prop_node_id},
            )

    _record_schema_change("UPDATE", name, f"Updated schema: {name}")
    return get_schema_node(name)


def get_schema_node(name: str) -> dict | None:
    """Return a single SchemaNode with its properties and relationships."""
    rows = run_cypher(
        "MATCH (sn:SchemaNode {name: $name}) "
        "OPTIONAL MATCH (sn)-[:HAS_PROPERTY]->(sp:SchemaProperty) "
        "OPTIONAL MATCH (sn)-[:HAS_RELATIONSHIP]->(sr:SchemaRelationship) "
        "RETURN sn.name AS name, sn.baseClass AS base_class, sn.layer AS layer, "
        "sn.version AS version, sn.isAbstract AS is_abstract, sn.createdAt AS created_at, "
        "collect(DISTINCT {name: sp.propertyName, dataType: sp.dataType, required: sp.required}) AS properties, "
        "collect(DISTINCT {name: sr.relName, type: sr.relationshipType, to: sr.toNodeName, cardinality: sr.cardinality}) AS relationships",
        {"name": name},
    )
    return rows[0] if rows else None


def get_schema_tree() -> dict:
    """Return full schema hierarchy grouped by base class."""
    rows = run_cypher(
        "MATCH (sn:SchemaNode) "
        "RETURN sn.name AS name, sn.baseClass AS base_class, "
        "sn.version AS version, sn.layer AS layer "
        "ORDER BY sn.baseClass, sn.name"
    )
    tree = {"Specification": [], "State": [], "Other": []}
    for row in rows:
        bc = row.get("base_class") or "Other"
        tree.setdefault(bc, []).append(row)
    return tree


def generate_class_code(schema_node_name: str) -> str:
    """Generate a Python neomodel class snippet for a schema node."""
    node = get_schema_node(schema_node_name)
    if node is None:
        return f"# SchemaNode '{schema_node_name}' not found."

    base = node.get("base_class", "Specification")
    props = node.get("properties", [])
    rels = node.get("relationships", [])

    lines = [
        "from neomodel import StructuredNode, StringProperty, FloatProperty, IntegerProperty, BooleanProperty, DateTimeFormatProperty, RelationshipTo",
        f"from newDigitalThreadLayer import {base}",
        "",
        "",
        f"class {schema_node_name}({base}):",
    ]

    type_map = {
        "string": "StringProperty()",
        "int": "IntegerProperty()",
        "float": "FloatProperty()",
        "bool": "BooleanProperty()",
        "datetime": "DateTimeFormatProperty(format='%Y-%m-%d %H:%M:%S')",
    }

    for prop in props:
        pname = prop.get("name") or ""
        dtype = (prop.get("dataType") or "string").lower()
        neomodel_type = type_map.get(dtype, "StringProperty()")
        if prop.get("required"):
            neomodel_type = neomodel_type.replace("()", "(required=True)")
        if pname:
            lines.append(f"    {pname} = {neomodel_type}")

    for rel in rels:
        rname = rel.get("name") or ""
        rtype = rel.get("type") or ""
        to_node = rel.get("to") or ""
        if rname and rtype and to_node:
            lines.append(
                f"    {rname.lower()} = RelationshipTo('{to_node}', '{rtype}')"
            )

    if len(lines) == 5:
        lines.append("    pass")

    return "\n".join(lines)


def get_schema_history() -> list:
    """Return all schema-type ChangeSets ordered by requestTime desc."""
    return run_cypher(
        "MATCH (cs:ChangeSet {changeType: 'SCHEMA'}) "
        "RETURN cs.identifier AS id, cs.title AS title, "
        "cs.status AS status, cs.requestTime AS request_time "
        "ORDER BY cs.requestTime DESC"
    )
