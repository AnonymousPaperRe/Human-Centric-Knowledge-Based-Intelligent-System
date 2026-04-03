"""
Spec Update Service — versioned spec update with automatic digital thread creation.

Supported action modes (aligned with newEventLayer.py reference):
  CREATE     — brand-new spec node
  UPDATE     — edit fields, bump version
  DELETE     — deprecate spec
  MERGE      — combine two+ specs into one
  SPLIT      — divide one spec into two+
  REPLACE    — swap one spec with an existing alternative
  RESEQUENCE — reorder WorkStepSpec sequence values

For all modes:
  - ChangeSet + ChangeAction created automatically
  - AFFECTS_OLD / AFFECTS_NEW linked
  - All non-versioning relationships re-wired to new node
  - Impact analysis run and returned
"""
from datetime import datetime
from services.neo4j_service import run_cypher
from services import impact_analysis_service


# ── Editable fields per spec type ────────────────────────────────────────────
SPEC_FIELDS: dict[str, list[str]] = {
    "Specification":                    ["name", "specType", "source", "sourceDoc", "notes"],
    "PartSpec":                         ["name", "status", "notes"],
    "EquipmentSpec":                    ["name", "manufacturer", "quota", "status", "notes"],
    "ManualToolSpec":                   ["name", "manufacturer", "quota", "notes"],
    "PrecisionToolSpec":                ["name", "manufacturer", "quota", "notes"],
    "RoboticEquipmentSpec":             ["name", "manufacturer", "notes"],
    "ProcessEquipmentSpec":             ["name", "manufacturer", "notes"],
    "DiagnosticEquipmentSpec":          ["name", "manufacturer", "notes"],
    "MaterialHandlingEquipmentSpec":    ["name", "manufacturer", "notes"],
    "WorkStepSpec":                     ["name", "instruction", "estimatedDuration", "sequence", "notes"],
    "OperationSpec":                    ["name", "notes"],
    "ProductionPlanSpec":               ["name", "plannedStartTime", "plannedEndTime", "plannedQuantity", "notes"],
    "ProductionOrderSpec":              ["name", "plannedStartTime", "plannedEndTime", "plannedQuantity", "notes"],
    "ProductDocumentSpec":              ["name", "notes"],
}

# Relationships that must NEVER be copied to a new version node
_SKIP_REL_TYPES = {
    "PREVIOUS_VERSION",
    "AFFECTS_OLD", "AFFECTS_NEW",
    "IMPACTS_SPECIFICATION",
    "IMPACTS_WORKSTEP_SPEC", "IMPACTS_PART_SPEC",
    "IMPACTS_EQUIPMENT_SPEC", "IMPACTS_OPERATION_SPEC",
    "IMPACTS_PROCESS", "IMPACTS_TASK",
    "IMPACTS_PART_INSTANCE", "IMPACTS_EQUIPMENT_INSTANCE",
    "IMPACTS_ORDER", "IMPACTS_VEHICLE", "IMPACTS_INVENTORY",
    "IMPACTS_ROLE",
    "CAUSED_BY", "HAS_ACTION",
}

IMMUTABLE_PARENTS = {"Specification", "State"}


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _bump_version(version: str | None) -> str:
    """Increment the patch segment: '1.0' → '1.1', '2.5' → '2.6'."""
    if not version:
        return "1.1"
    parts = version.split(".")
    try:
        parts[-1] = str(int(parts[-1]) + 1)
    except ValueError:
        parts.append("1")
    return ".".join(parts)


def get_editable_fields(spec_type: str) -> list[str]:
    """Return the list of user-editable fields for a given spec type."""
    for t in [spec_type, "Specification"]:
        if t in SPEC_FIELDS:
            return SPEC_FIELDS[t]
    return SPEC_FIELDS["Specification"]


def get_spec(identifier: str) -> dict | None:
    """Return a spec node as {labels, props} or None."""
    rows = run_cypher(
        "MATCH (s:Specification {identifier: $id}) "
        "RETURN labels(s) AS labels, properties(s) AS props",
        {"id": identifier},
    )
    if not rows:
        return None
    row = rows[0]
    props = row.get("props") or {}
    if isinstance(props, dict) and "props" in props and isinstance(props["props"], dict):
        props = props["props"]
    return {"labels": row.get("labels", []), "props": props}


def _primary_label(labels: list[str]) -> str:
    """Return the most specific label (not 'Specification' unless it's the only one)."""
    non_base = [lb for lb in labels if lb != "Specification"]
    return non_base[-1] if non_base else "Specification"


def _rewire_relationships(old_identifier: str, new_identifier: str):
    """Re-wire all non-versioning relationships from old spec to new spec."""
    # Incoming: other nodes pointing TO old spec
    incoming_rels = run_cypher(
        "MATCH (src)-[r]->(old:Specification {identifier: $old_id}) "
        "WHERE NOT type(r) IN $skip "
        "RETURN DISTINCT type(r) AS rel_type",
        {"old_id": old_identifier, "skip": list(_SKIP_REL_TYPES)},
    )
    for row in incoming_rels:
        rel_type = row.get("rel_type")
        if rel_type:
            run_cypher(
                f"MATCH (src)-[:{rel_type}]->(old:Specification {{identifier: $old_id}}) "
                f"MATCH (new:Specification {{identifier: $new_id}}) "
                f"MERGE (src)-[:{rel_type}]->(new)",
                {"old_id": old_identifier, "new_id": new_identifier},
            )

    # Outgoing: old spec pointing TO other (non-Spec) nodes
    outgoing_rels = run_cypher(
        "MATCH (old:Specification {identifier: $old_id})-[r]->(tgt) "
        "WHERE NOT type(r) IN $skip AND NOT tgt:Specification "
        "RETURN DISTINCT type(r) AS rel_type",
        {"old_id": old_identifier, "skip": list(_SKIP_REL_TYPES)},
    )
    for row in outgoing_rels:
        rel_type = row.get("rel_type")
        if rel_type:
            run_cypher(
                f"MATCH (old:Specification {{identifier: $old_id}})-[:{rel_type}]->(tgt) "
                f"WHERE NOT tgt:Specification "
                f"MATCH (new:Specification {{identifier: $new_id}}) "
                f"MERGE (new)-[:{rel_type}]->(tgt)",
                {"old_id": old_identifier, "new_id": new_identifier},
            )


def _make_changeset(cs_id: str, title: str, change_type: str, author: str, now: str):
    run_cypher(
        "MERGE (cs:ChangeSet {identifier: $cs_id}) "
        "SET cs.title = $title, cs.changeType = $ct, cs.status = 'IMPLEMENTED', "
        "cs.owner = $author, cs.requestTime = $now",
        {"cs_id": cs_id, "title": title, "ct": change_type, "author": author, "now": now},
    )


def _make_changeaction(
    ca_id: str, action_type: str, reason: str, sequence: int, now: str
):
    run_cypher(
        "MERGE (ca:ChangeAction {identifier: $ca_id}) "
        "SET ca.actionType = $at, ca.reason = $reason, "
        "ca.status = 'DONE', ca.createTime = $now, ca.sequence = $seq",
        {"ca_id": ca_id, "at": action_type, "reason": reason, "now": now, "seq": sequence},
    )


def _link_cs_ca(cs_id: str, ca_id: str, sequence: int = 1):
    run_cypher(
        "MATCH (cs:ChangeSet {identifier: $cs_id}), (ca:ChangeAction {identifier: $ca_id}) "
        "MERGE (cs)-[:HAS_ACTION {sequence: $seq}]->(ca)",
        {"cs_id": cs_id, "ca_id": ca_id, "seq": sequence},
    )


def _link_affects_old(ca_id: str, spec_id: str):
    run_cypher(
        "MATCH (ca:ChangeAction {identifier: $ca_id}), "
        "(s:Specification {identifier: $sid}) "
        "MERGE (ca)-[:AFFECTS_OLD]->(s)",
        {"ca_id": ca_id, "sid": spec_id},
    )


def _link_affects_new(ca_id: str, spec_id: str):
    run_cypher(
        "MATCH (ca:ChangeAction {identifier: $ca_id}), "
        "(s:Specification {identifier: $sid}) "
        "MERGE (ca)-[:AFFECTS_NEW]->(s)",
        {"ca_id": ca_id, "sid": spec_id},
    )


def _safe_id(s: str) -> str:
    """Strip spaces and colons from a string for use in identifiers."""
    return s.replace(" ", "T").replace(":", "").replace("-", "")


# ═════════════════════════════════════════════════════════════════════════════
# CREATE
# ═════════════════════════════════════════════════════════════════════════════

def create_spec(
    spec_type: str,
    identifier: str,
    properties: dict,
    reason: str = "New specification created via KBS",
    change_type: str = "DESIGN",
    author: str = "KBS User",
    change_set_id: str | None = None,
) -> dict:
    """Create a brand-new spec node with an initial ChangeSet + ChangeAction."""
    now = _now_str()

    if spec_type in IMMUTABLE_PARENTS:
        raise ValueError(
            f"Cannot create instances of immutable class '{spec_type}' directly."
        )

    # Build properties
    props = {**properties}
    props["identifier"] = identifier
    props["version"] = "1.0"
    props["status"] = "ACTIVE"
    props["validFrom"] = now
    props["validTo"] = None
    props["createTime"] = now

    filtered = {k: v for k, v in props.items() if v is not None}
    set_clauses = ", ".join(f"n.{k} = ${k}" for k in filtered)
    run_cypher(
        f"CREATE (n:{spec_type}:Specification) SET {set_clauses}",
        filtered,
    )

    cs_id = change_set_id or f"CS-CREATE-{identifier}-{_safe_id(now)}"
    _make_changeset(cs_id, f"Create {identifier}", change_type, author, now)

    ca_id = f"CA-CREATE-{identifier}-{_safe_id(now)}"
    _make_changeaction(ca_id, "CREATE", reason, 1, now)
    _link_cs_ca(cs_id, ca_id)
    _link_affects_new(ca_id, identifier)

    return {
        "identifier": identifier,
        "version": "1.0",
        "change_set_id": cs_id,
        "change_action_id": ca_id,
        "author": author,
    }


# ═════════════════════════════════════════════════════════════════════════════
# UPDATE
# ═════════════════════════════════════════════════════════════════════════════

def update_spec(
    identifier: str,
    updated_fields: dict,
    reason: str = "Manual update via KBS",
    change_type: str = "DESIGN",
    author: str = "KBS User",
    change_set_id: str | None = None,
) -> dict:
    """
    Create a versioned spec update:
      1. Load existing spec + snapshot editable fields
      2. Create new spec node (bumped version, versioned identifier)
      3. Deprecate old spec
      4. PREVIOUS_VERSION relationship
      5. Re-wire all non-versioning relationships to new node
      6. ChangeSet + ChangeAction + AFFECTS_OLD/NEW
      7. Impact analysis
    Returns full result dict with diff.
    """
    now = _now_str()

    existing = get_spec(identifier)
    if existing is None:
        raise ValueError(f"Specification '{identifier}' not found.")

    old_props = existing["props"]
    labels = existing["labels"]
    primary_label = _primary_label(labels)

    if set(labels) == {"Specification"} or set(labels) == {"State"}:
        raise ValueError(f"Cannot update immutable parent class '{labels[0]}' directly.")

    editable = get_editable_fields(primary_label)
    from_fields = {k: old_props.get(k) for k in editable if k in old_props}
    changed_fields = {k: v for k, v in updated_fields.items() if k in editable}

    old_version = old_props.get("version", "1.0")
    new_version = _bump_version(old_version)
    new_identifier = f"{identifier}-v{new_version}"

    new_props = {**old_props, **changed_fields}
    new_props["identifier"] = new_identifier
    new_props["version"] = new_version
    new_props["validFrom"] = now
    new_props["validTo"] = None
    new_props["status"] = "ACTIVE"
    new_props["createTime"] = now

    filtered = {k: v for k, v in new_props.items() if v is not None}
    set_clauses = ", ".join(f"n.{k} = ${k}" for k in filtered)
    run_cypher(
        f"CREATE (n:{primary_label}:Specification) SET {set_clauses}",
        filtered,
    )

    run_cypher(
        "MATCH (s:Specification {identifier: $id}) "
        "SET s.status = 'DEPRECATED', s.validTo = $now",
        {"id": identifier, "now": now},
    )

    run_cypher(
        "MATCH (new_s:Specification {identifier: $new_id}), "
        "(old_s:Specification {identifier: $old_id}) "
        "MERGE (new_s)-[r:PREVIOUS_VERSION]->(old_s) SET r.reason = $reason",
        {"new_id": new_identifier, "old_id": identifier, "reason": reason},
    )

    _rewire_relationships(identifier, new_identifier)

    cs_id = change_set_id or f"CS-{identifier}-{_safe_id(now)}"
    _make_changeset(
        cs_id,
        f"Update {identifier} → {new_identifier}",
        change_type, author, now,
    )

    ca_id = f"CA-{new_identifier}-{_safe_id(now)}"
    _make_changeaction(ca_id, "UPDATE", reason, 1, now)
    _link_cs_ca(cs_id, ca_id)
    _link_affects_old(ca_id, identifier)
    _link_affects_new(ca_id, new_identifier)

    impact_report = impact_analysis_service.run(
        change_action_id=ca_id,
        spec_identifier=identifier,
        spec_type=primary_label,
    )

    return {
        "old_identifier": identifier,
        "new_identifier": new_identifier,
        "old_version": old_version,
        "new_version": new_version,
        "change_set_id": cs_id,
        "change_action_id": ca_id,
        "author": author,
        "from_fields": from_fields,
        "changed_fields": changed_fields,
        "impacts": impact_report,
    }


# ═════════════════════════════════════════════════════════════════════════════
# DELETE (deprecate)
# ═════════════════════════════════════════════════════════════════════════════

def delete_spec(
    identifier: str,
    reason: str = "Specification removed via KBS",
    change_type: str = "DESIGN",
    author: str = "KBS User",
    change_set_id: str | None = None,
) -> dict:
    """Deprecate a spec and record the action in the digital thread."""
    now = _now_str()

    existing = get_spec(identifier)
    if existing is None:
        raise ValueError(f"Specification '{identifier}' not found.")

    labels = existing["labels"]
    primary_label = _primary_label(labels)

    if set(labels) == {"Specification"} or set(labels) == {"State"}:
        raise ValueError(f"Cannot delete immutable parent class '{labels[0]}'.")

    run_cypher(
        "MATCH (s:Specification {identifier: $id}) "
        "SET s.status = 'DEPRECATED', s.validTo = $now",
        {"id": identifier, "now": now},
    )

    cs_id = change_set_id or f"CS-DEL-{identifier}-{_safe_id(now)}"
    _make_changeset(cs_id, f"Remove {identifier}", change_type, author, now)

    ca_id = f"CA-DEL-{identifier}-{_safe_id(now)}"
    _make_changeaction(ca_id, "REMOVE", reason, 1, now)
    _link_cs_ca(cs_id, ca_id)
    _link_affects_old(ca_id, identifier)

    impact_report = impact_analysis_service.run(
        change_action_id=ca_id,
        spec_identifier=identifier,
        spec_type=primary_label,
    )

    return {
        "identifier": identifier,
        "change_set_id": cs_id,
        "change_action_id": ca_id,
        "author": author,
        "impacts": impact_report,
    }


# ═════════════════════════════════════════════════════════════════════════════
# MERGE
# ═════════════════════════════════════════════════════════════════════════════

def merge_specs(
    source_identifiers: list[str],
    merged_identifier: str,
    merged_name: str,
    extra_props: dict | None = None,
    reason: str = "Specifications merged via KBS",
    change_type: str = "PROCESS",
    author: str = "KBS User",
    change_set_id: str | None = None,
) -> dict:
    """
    Merge two or more specs into a new merged spec.
    Both sources are deprecated; all relationships re-wired to merged node.
    """
    now = _now_str()

    sources = []
    for sid in source_identifiers:
        s = get_spec(sid)
        if s is None:
            raise ValueError(f"Source spec '{sid}' not found.")
        sources.append(s)

    primary_label = _primary_label(sources[0]["labels"])

    base_props = {**sources[0]["props"]}
    base_props.update(extra_props or {})
    base_props["identifier"] = merged_identifier
    base_props["name"] = merged_name
    base_props["version"] = "1.0"
    base_props["status"] = "ACTIVE"
    base_props["validFrom"] = now
    base_props["validTo"] = None
    base_props["createTime"] = now

    filtered = {k: v for k, v in base_props.items() if v is not None}
    set_clauses = ", ".join(f"n.{k} = ${k}" for k in filtered)
    run_cypher(
        f"CREATE (n:{primary_label}:Specification) SET {set_clauses}",
        filtered,
    )

    for sid in source_identifiers:
        run_cypher(
            "MATCH (s:Specification {identifier: $id}) "
            "SET s.status = 'DEPRECATED', s.validTo = $now",
            {"id": sid, "now": now},
        )
        run_cypher(
            "MATCH (new_s:Specification {identifier: $new_id}), "
            "(old_s:Specification {identifier: $old_id}) "
            "MERGE (new_s)-[r:PREVIOUS_VERSION]->(old_s) SET r.reason = $reason",
            {"new_id": merged_identifier, "old_id": sid, "reason": reason},
        )
        _rewire_relationships(sid, merged_identifier)

    cs_id = change_set_id or f"CS-MERGE-{merged_identifier}-{_safe_id(now)}"
    _make_changeset(
        cs_id,
        f"Merge {', '.join(source_identifiers)} → {merged_identifier}",
        change_type, author, now,
    )

    ca_id = f"CA-MERGE-{merged_identifier}-{_safe_id(now)}"
    _make_changeaction(ca_id, "MERGE", reason, 1, now)
    _link_cs_ca(cs_id, ca_id)

    for sid in source_identifiers:
        _link_affects_old(ca_id, sid)
    _link_affects_new(ca_id, merged_identifier)

    impact_report = impact_analysis_service.run(
        change_action_id=ca_id,
        spec_identifier=source_identifiers[0],
        spec_type=primary_label,
    )

    return {
        "merged_identifier": merged_identifier,
        "source_identifiers": source_identifiers,
        "change_set_id": cs_id,
        "change_action_id": ca_id,
        "author": author,
        "impacts": impact_report,
    }


# ═════════════════════════════════════════════════════════════════════════════
# SPLIT
# ═════════════════════════════════════════════════════════════════════════════

def split_spec(
    source_identifier: str,
    split_specs: list[dict],
    reason: str = "Specification split via KBS",
    change_type: str = "PROCESS",
    author: str = "KBS User",
    change_set_id: str | None = None,
) -> dict:
    """
    Split one spec into two or more new specs.
    split_specs: [{"identifier": str, "name": str, "props": dict}, ...]
    Source is deprecated; each new spec gets AFFECTS_NEW.
    Relationships re-wired to the first new spec (primary successor).
    """
    now = _now_str()

    existing = get_spec(source_identifier)
    if existing is None:
        raise ValueError(f"Source spec '{source_identifier}' not found.")

    labels = existing["labels"]
    primary_label = _primary_label(labels)
    source_props = existing["props"]

    new_identifiers = []
    for i, spec_def in enumerate(split_specs):
        new_id = spec_def["identifier"]
        new_identifiers.append(new_id)

        new_props = {**source_props, **spec_def.get("props", {})}
        new_props["identifier"] = new_id
        new_props["name"] = spec_def.get("name", new_id)
        new_props["version"] = "1.0"
        new_props["status"] = "ACTIVE"
        new_props["validFrom"] = now
        new_props["validTo"] = None
        new_props["createTime"] = now

        filtered = {k: v for k, v in new_props.items() if v is not None}
        set_clauses = ", ".join(f"n.{k} = ${k}" for k in filtered)
        run_cypher(
            f"CREATE (n:{primary_label}:Specification) SET {set_clauses}",
            filtered,
        )
        run_cypher(
            "MATCH (new_s:Specification {identifier: $new_id}), "
            "(old_s:Specification {identifier: $old_id}) "
            "MERGE (new_s)-[r:PREVIOUS_VERSION]->(old_s) SET r.reason = $reason",
            {"new_id": new_id, "old_id": source_identifier, "reason": reason},
        )

    run_cypher(
        "MATCH (s:Specification {identifier: $id}) "
        "SET s.status = 'DEPRECATED', s.validTo = $now",
        {"id": source_identifier, "now": now},
    )

    # Re-wire existing relationships to first successor
    if new_identifiers:
        _rewire_relationships(source_identifier, new_identifiers[0])

    cs_id = change_set_id or f"CS-SPLIT-{source_identifier}-{_safe_id(now)}"
    _make_changeset(
        cs_id,
        f"Split {source_identifier} → {', '.join(new_identifiers)}",
        change_type, author, now,
    )

    ca_id = f"CA-SPLIT-{source_identifier}-{_safe_id(now)}"
    _make_changeaction(ca_id, "SPLIT", reason, 1, now)
    _link_cs_ca(cs_id, ca_id)
    _link_affects_old(ca_id, source_identifier)
    for new_id in new_identifiers:
        _link_affects_new(ca_id, new_id)

    impact_report = impact_analysis_service.run(
        change_action_id=ca_id,
        spec_identifier=source_identifier,
        spec_type=primary_label,
    )

    return {
        "source_identifier": source_identifier,
        "new_identifiers": new_identifiers,
        "change_set_id": cs_id,
        "change_action_id": ca_id,
        "author": author,
        "impacts": impact_report,
    }


# ═════════════════════════════════════════════════════════════════════════════
# REPLACE
# ═════════════════════════════════════════════════════════════════════════════

def replace_spec(
    old_identifier: str,
    replacement_identifier: str,
    reason: str = "Specification replaced via KBS",
    change_type: str = "SUPPLIER",
    author: str = "KBS User",
    change_set_id: str | None = None,
) -> dict:
    """
    Replace one spec with an existing alternative (e.g. supplier part change).
    Old spec is deprecated; relationships re-wired to the replacement.
    """
    now = _now_str()

    old = get_spec(old_identifier)
    if old is None:
        raise ValueError(f"Specification '{old_identifier}' not found.")
    if get_spec(replacement_identifier) is None:
        raise ValueError(f"Replacement '{replacement_identifier}' not found.")

    labels = old["labels"]
    primary_label = _primary_label(labels)

    run_cypher(
        "MATCH (s:Specification {identifier: $id}) "
        "SET s.status = 'DEPRECATED', s.validTo = $now",
        {"id": old_identifier, "now": now},
    )
    run_cypher(
        "MATCH (new_s:Specification {identifier: $new_id}), "
        "(old_s:Specification {identifier: $old_id}) "
        "MERGE (new_s)-[r:PREVIOUS_VERSION]->(old_s) SET r.reason = $reason",
        {"new_id": replacement_identifier, "old_id": old_identifier, "reason": reason},
    )
    _rewire_relationships(old_identifier, replacement_identifier)

    cs_id = change_set_id or f"CS-REPL-{old_identifier}-{_safe_id(now)}"
    _make_changeset(
        cs_id,
        f"Replace {old_identifier} → {replacement_identifier}",
        change_type, author, now,
    )

    ca_id = f"CA-REPL-{old_identifier}-{_safe_id(now)}"
    _make_changeaction(ca_id, "REPLACE", reason, 1, now)
    _link_cs_ca(cs_id, ca_id)
    _link_affects_old(ca_id, old_identifier)
    _link_affects_new(ca_id, replacement_identifier)

    impact_report = impact_analysis_service.run(
        change_action_id=ca_id,
        spec_identifier=old_identifier,
        spec_type=primary_label,
    )

    return {
        "old_identifier": old_identifier,
        "replacement_identifier": replacement_identifier,
        "change_set_id": cs_id,
        "change_action_id": ca_id,
        "author": author,
        "impacts": impact_report,
    }


# ═════════════════════════════════════════════════════════════════════════════
# RESEQUENCE (WorkStepSpec)
# ═════════════════════════════════════════════════════════════════════════════

def resequence_steps(
    step_sequence: list[dict],
    reason: str = "Workstep resequencing via KBS",
    change_type: str = "PROCESS",
    author: str = "KBS User",
    change_set_id: str | None = None,
) -> dict:
    """
    Resequence WorkStepSpec nodes: apply new sequence numbers, creating
    versioned updates for each changed step.
    step_sequence: [{"identifier": str, "new_sequence": int}, ...]
    """
    now = _now_str()

    cs_id = change_set_id or f"CS-RESEQ-{_safe_id(now)}"
    _make_changeset(cs_id, "Resequence work steps", change_type, author, now)

    updated = []
    for i, step in enumerate(step_sequence):
        sid = step["identifier"]
        new_seq = step["new_sequence"]

        existing = get_spec(sid)
        if existing is None:
            continue

        result = update_spec(
            identifier=sid,
            updated_fields={"sequence": new_seq},
            reason=reason,
            change_type=change_type,
            author=author,
            change_set_id=cs_id,
        )
        updated.append(result)

    return {
        "change_set_id": cs_id,
        "author": author,
        "resequenced": updated,
    }


# ═════════════════════════════════════════════════════════════════════════════
# READ helpers
# ═════════════════════════════════════════════════════════════════════════════

def get_digital_thread(identifier: str) -> list:
    """Return the full version chain for a spec (newest → oldest)."""
    rows = run_cypher(
        "MATCH path = (s:Specification {identifier: $id})"
        "-[:PREVIOUS_VERSION*0..20]->(old:Specification) "
        "RETURN [n IN nodes(path) | {"
        "  identifier: n.identifier, version: n.version, "
        "  status: n.status, validFrom: n.validFrom, validTo: n.validTo"
        "}] AS chain",
        {"id": identifier},
    )
    return rows[0]["chain"] if rows else []


def get_change_actions_for_spec(identifier: str) -> list:
    """Return all ChangeActions that affected this spec (old or new side)."""
    return run_cypher(
        "MATCH (ca:ChangeAction)-[:AFFECTS_OLD|AFFECTS_NEW]->"
        "(s:Specification {identifier: $id}) "
        "OPTIONAL MATCH (cs:ChangeSet)-[:HAS_ACTION]->(ca) "
        "RETURN ca.identifier AS ca_id, ca.actionType AS action_type, "
        "ca.reason AS reason, ca.createTime AS create_time, ca.status AS ca_status, "
        "cs.identifier AS cs_id, cs.changeType AS change_type, "
        "cs.status AS cs_status, cs.owner AS author "
        "ORDER BY ca.createTime DESC",
        {"id": identifier},
    )
