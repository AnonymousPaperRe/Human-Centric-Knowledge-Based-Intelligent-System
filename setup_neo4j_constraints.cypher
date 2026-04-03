// =============================================================================
// AUTOAM — Neo4j Constraint & Index Setup
// Run this script once against your Neo4j instance BEFORE loading any data.
// Tested on Neo4j 4.x Community Edition.
//
// Usage (neo4j-shell / cypher-shell):
//   cypher-shell -u neo4j -p <password> < setup_neo4j_constraints.cypher
// Or paste block-by-block in Neo4j Browser.
// =============================================================================

// ── Product Design Layer ──────────────────────────────────────────────────────
CREATE CONSTRAINT productdocument_id IF NOT EXISTS
  FOR (n:ProductDocument) REQUIRE n.identifier IS UNIQUE;

// ── Plant Organization Layer ──────────────────────────────────────────────────
// (ManufacturingPlant, ProductionShop, ProductionPlan, ProductionOrder have no
//  unique_index declared in the model, but adding them is recommended)

// ── Process Plan Layer ────────────────────────────────────────────────────────
CREATE CONSTRAINT part_id IF NOT EXISTS
  FOR (n:Part) REQUIRE n.identifier IS UNIQUE;

CREATE CONSTRAINT tool_id IF NOT EXISTS
  FOR (n:Tool) REQUIRE n.identifier IS UNIQUE;

CREATE CONSTRAINT equipment_id IF NOT EXISTS
  FOR (n:Equipment) REQUIRE n.identifier IS UNIQUE;

CREATE CONSTRAINT operation_id IF NOT EXISTS
  FOR (n:Operation) REQUIRE n.identifier IS UNIQUE;

// ── Digital Thread Layer — Specifications ─────────────────────────────────────
CREATE CONSTRAINT specification_id IF NOT EXISTS
  FOR (n:Specification) REQUIRE n.identifier IS UNIQUE;

// ── Digital Thread Layer — Versions ──────────────────────────────────────────
CREATE CONSTRAINT version_id IF NOT EXISTS
  FOR (n:Version) REQUIRE n.identifier IS UNIQUE;

// ── Digital Thread Layer — States ─────────────────────────────────────────────
// State is the parent; subclasses (ProductionProcessState, PersonnelState,
// EquipmentState) inherit the constraint via the same label.

// ── Event Layer ───────────────────────────────────────────────────────────────
CREATE CONSTRAINT changeset_id IF NOT EXISTS
  FOR (n:ChangeSet) REQUIRE n.identifier IS UNIQUE;

CREATE CONSTRAINT changeaction_id IF NOT EXISTS
  FOR (n:ChangeAction) REQUIRE n.identifier IS UNIQUE;

CREATE CONSTRAINT effectivityscope_id IF NOT EXISTS
  FOR (n:EffectivityScope) REQUIRE n.identifier IS UNIQUE;

// ── Schema Meta-Graph ─────────────────────────────────────────────────────────
CREATE CONSTRAINT schemanode_name IF NOT EXISTS
  FOR (n:SchemaNode) REQUIRE n.name IS UNIQUE;

// ── Optional: enable APOC (required for kg_schema_service) ───────────────────
// Verify APOC is installed:
//   RETURN apoc.version();
// If not installed, download the matching APOC jar from:
//   https://github.com/neo4j-contrib/neo4j-apoc-procedures/releases
// and place it in <neo4j-home>/plugins/, then restart Neo4j.
