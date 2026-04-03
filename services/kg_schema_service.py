"""
KG Schema Service — loads the live Neo4j schema once and exposes
entity-specific sub-schema extraction for Cypher generation prompts.

Usage:
    from services.kg_schema_service import get_subschema_for_entities
    schema_str = get_subschema_for_entities(["ProductionProcess", "Vehicle"])
    # Inject schema_str into LLM system prompt before Cypher generation.
"""
from urllib.parse import urlparse
from config import NEO4J_BOLT
from services import neo4j_service

_jschema = None   # lazy-loaded singleton


def _parse_bolt_url(bolt_url: str) -> tuple[str, str, str]:
    """Parse bolt://user:password@host:port → (uri, username, password)."""
    parsed = urlparse(bolt_url)
    uri      = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
    username = parsed.username or "neo4j"
    password = parsed.password or ""
    return uri, username, password


def _load_jschema() -> dict:
    """Load structured schema from Neo4j (called once, result cached)."""
    global _jschema
    if _jschema is not None:
        return _jschema
    try:
        from utils.neo4j_schema import Neo4jSchema
        uri, username, password = _parse_bolt_url(NEO4J_BOLT)
        ns = Neo4jSchema(uri, username, password)
        _jschema = ns.get_structured_schema
    except Exception:
        _jschema = {"node_props": {}, "rel_props": {}, "relationships": []}
    return _jschema


def get_subschema_by_hops(labels: list[str], hops: int = 2) -> str:
    """
    Build a schema string by BFS from seed `labels` in the schema relationship graph,
    collecting all nodes reachable within `hops` steps.

    For two seed labels, also finds nodes on the shortest schema path between them so
    the LLM sees the full connecting chain (e.g. ProductionPlan → ProductionPlanVersion
    → ProductionOrderVersion → ProductionOrder).

    Replaces the Levenshtein-based approach: we know the exact labels from NER, so
    graph-hop neighborhood is far more reliable than string similarity.
    """
    jschema = _load_jschema()
    node_props = jschema.get("node_props", {})
    relationships = jschema.get("relationships", [])
    if not node_props or not relationships:
        return ""

    # Build undirected adjacency on the schema graph
    adjacency: dict[str, list[tuple[str, str]]] = {}
    for rel in relationships:
        if isinstance(rel.get("type"), dict):
            continue
        s, t, e = rel["start"], rel["type"], rel["end"]
        adjacency.setdefault(s, []).append((t, e))
        adjacency.setdefault(e, []).append((t, s))

    # BFS from each seed label up to `hops` steps
    visited: set[str] = set()
    queue: list[tuple[str, int]] = []
    for lbl in labels:
        if lbl in node_props:
            visited.add(lbl)
            queue.append((lbl, 0))

    while queue:
        node, depth = queue.pop(0)
        if depth >= hops:
            continue
        for _, neighbor in adjacency.get(node, []):
            if neighbor not in visited and neighbor in node_props:
                visited.add(neighbor)
                queue.append((neighbor, depth + 1))

    # For two seed labels, add nodes on the shortest path between them
    if len(labels) == 2:
        a, b = labels[0], labels[1]
        if a in node_props and b in node_props and a != b:
            # BFS shortest path a → b
            prev: dict[str, str | None] = {a: None}
            bfs: list[str] = [a]
            found = False
            while bfs and not found:
                nxt: list[str] = []
                for node in bfs:
                    for _, nb in adjacency.get(node, []):
                        if nb not in prev:
                            prev[nb] = node
                            nxt.append(nb)
                            if nb == b:
                                found = True
                                break
                    if found:
                        break
                bfs = nxt
            if found:
                cur: str | None = b
                while cur is not None:
                    if cur in node_props:
                        visited.add(cur)
                    cur = prev.get(cur)

    if not visited:
        return ""

    # Format node properties
    node_parts: list[str] = []
    for lbl in sorted(visited):
        props = node_props.get(lbl, [])
        props_str = ", ".join(f"{p['property']}: {p['datatype']}" for p in props)
        node_parts.append(f"{lbl} {{{props_str}}}")

    # Format relationships (both ends in visited)
    rel_props_map = jschema.get("rel_props", {})
    seen_keys: set[str] = set()
    seen_rtypes: set[str] = set()
    rel_parts: list[str] = []
    rel_prop_parts: list[str] = []
    for rel in relationships:
        if isinstance(rel.get("type"), dict):
            continue
        if rel["start"] in visited and rel["end"] in visited:
            key = f"(:{rel['start']})-[:{rel['type']}]->(:{rel['end']})"
            if key not in seen_keys:
                seen_keys.add(key)
                rel_parts.append(key)
            rtype = rel["type"]
            if rtype not in seen_rtypes and rtype in rel_props_map:
                seen_rtypes.add(rtype)
                rprops = rel_props_map[rtype]
                props_str = ", ".join(f"{p['property']}: {p['datatype']}" for p in rprops)
                if props_str:
                    rel_prop_parts.append(f"{rtype} {{{props_str}}}")

    return "\n".join([
        "Node properties are the following:",
        ", ".join(node_parts),
        "Relationship properties are the following:",
        ", ".join(rel_prop_parts) if rel_prop_parts else "(none)",
        "The relationships are the following:",
        ", ".join(rel_parts),
    ])


def get_instance_neighborhood_schema(entity_pairs: list[tuple[str, str]], hops: int = 2) -> str:
    """
    Build a schema string from the ACTUAL 2-hop neighborhood of specific node instances
    in the live graph, rather than BFS across the static schema graph.

    For each (label, identifier) pair with a real ID:
      1. Query Neo4j for all node labels and relationship types reachable within `hops` steps
      2. Collect the unique label set from the real data
      3. Look up property definitions for those labels from the cached jschema
      4. Format as the standard schema string

    For type-hint pairs (empty ID), fall back to 1-hop static schema BFS.
    This approach is bounded by the actual graph topology around the queried node,
    never expanding to the full schema.
    """
    jschema = _load_jschema()
    node_props = jschema.get("node_props", {})
    relationships = jschema.get("relationships", [])

    found_labels: set[str] = set()
    found_rel_keys: set[tuple[str, str, str]] = set()  # (start, type, end)

    real_pairs = [(lbl, eid) for lbl, eid in entity_pairs if eid and lbl and lbl != "Unknown"]
    hint_pairs = [(lbl, eid) for lbl, eid in entity_pairs if not eid and lbl and lbl != "Unknown"]

    # ── Live instance query ────────────────────────────────────────────────────
    for label, eid in real_pairs:
        cypher = (
            f"MATCH path = (n:{label} {{identifier: $id}})-[*1..{hops}]-(m) "
            "WITH n, relationships(path) AS rels, nodes(path) AS nds "
            "UNWIND nds AS nd "
            "WITH n, nd, rels "
            "RETURN DISTINCT "
            "  labels(n)  AS src_labels, "
            "  labels(nd) AS nbr_labels, "
            "  [r IN rels | type(r)] AS rel_types "
            "LIMIT 200"
        )
        result = neo4j_service.safe_run(cypher, {"id": eid})
        if result.get("ok") and result.get("data"):
            for row in result["data"]:
                for lbl_list in (row.get("src_labels") or [], row.get("nbr_labels") or []):
                    for lbl in lbl_list:
                        found_labels.add(lbl)
                for rtype in (row.get("rel_types") or []):
                    found_labels.discard(None)
                    # record rel type for filtering below
                    found_rel_keys.add(rtype)
        else:
            # Instance not found or query failed — fall back to 1-hop static BFS
            found_labels.add(label)

    # ── Static 1-hop fallback for type-hint labels ─────────────────────────────
    if hint_pairs or not real_pairs:
        fallback_labels = [lbl for lbl, _ in hint_pairs] or [lbl for lbl, _ in entity_pairs if lbl]
        static = get_subschema_by_hops(fallback_labels, hops=1)
        if static:
            return static  # return immediately for hint-only queries

    if not found_labels:
        return ""

    # ── Format node properties ─────────────────────────────────────────────────
    node_parts: list[str] = []
    for lbl in sorted(found_labels):
        props = node_props.get(lbl, [])
        if props:
            props_str = ", ".join(f"{p['property']}: {p['datatype']}" for p in props)
            node_parts.append(f"{lbl} {{{props_str}}}")

    # ── Format relationships (both endpoints in found_labels) ──────────────────
    rel_props_map = jschema.get("rel_props", {})
    seen_rel_keys: set[str] = set()
    seen_rtypes: set[str] = set()
    rel_parts: list[str] = []
    rel_prop_parts: list[str] = []
    for rel in relationships:
        if isinstance(rel.get("type"), dict):
            continue
        if rel["start"] in found_labels and rel["end"] in found_labels:
            key = f"(:{rel['start']})-[:{rel['type']}]->(:{rel['end']})"
            if key not in seen_rel_keys:
                seen_rel_keys.add(key)
                rel_parts.append(key)
            rtype = rel["type"]
            if rtype not in seen_rtypes and rtype in rel_props_map:
                seen_rtypes.add(rtype)
                rprops = rel_props_map[rtype]
                props_str = ", ".join(f"{p['property']}: {p['datatype']}" for p in rprops)
                if props_str:
                    rel_prop_parts.append(f"{rtype} {{{props_str}}}")

    return "\n".join([
        "Node properties are the following:",
        ", ".join(node_parts) if node_parts else "(none)",
        "Relationship properties are the following:",
        ", ".join(rel_prop_parts) if rel_prop_parts else "(none)",
        "The relationships are the following:",
        ", ".join(rel_parts) if rel_parts else "(none)",
    ])


def get_subschema_for_entities(labels: list[str], lev_dist: int = 2) -> str:
    """
    Return a formatted schema string covering all nodes and relationships
    within Levenshtein distance `lev_dist` of each label in `labels`.

    Used to inject precise KG schema into the LLM system prompt before
    Cypher generation, replacing the coarse hand-written SCHEMA_SUMMARY.

    Example:
        get_subschema_for_entities(["ProductionProcess", "Vehicle"])
        →
        Node properties are the following:
        ProductionProcess {identifier: STRING, ...}, Vehicle {identifier: STRING, ...}
        Relationship properties are the following:
        ...
        The relationships are the following:
        (:ProductionProcess)-[:PRODUCES_VEHICLE]->(:Vehicle), ...
    """
    if not labels:
        return ""
    jschema = _load_jschema()
    if not jschema.get("node_props"):
        return ""
    try:
        from utils.graph_utils import get_subgraph_schema
        return get_subgraph_schema(jschema, labels, lev_dist, formatted=True)
    except Exception:
        return ""
