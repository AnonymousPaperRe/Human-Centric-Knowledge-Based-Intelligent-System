# AUTOAM — Automotive Knowledge-Based System

A graph-based knowledge management system for automotive manufacturing, powered by **Neo4j**, **neomodel**, **Streamlit**, and **OpenAI GPT-4o**.

The system models the full manufacturing digital thread — from product design and process planning through production execution — and exposes it through a conversational AI agent backed by deterministic graph primitives and a HITL (Human-in-the-Loop) resolution pipeline.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────┐
│              Streamlit UI (app.py)               │
│   Agent Chat │ Query Templates │ Cypher Query    │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│           Agent Pipeline (agent/)                │
│  NER → Rewrite → NER2 → Routing → Tool Execution│
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│           Services (services/)                   │
│  Neo4j · SpecUpdate · Memory · Templates · Schema│
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│           Neo4j Graph Database                   │
│  Domain layers modelled with neomodel ORM        │
└─────────────────────────────────────────────────┘
```

### Domain Layers (read-only — do not modify)

| File | Key node types |
|------|---------------|
| `ProductDesignLayer.py` | `VehicleFamily`, `VehicleVariant`, `ProductDocument` |
| `PlantOrganizationLayer.py` | `ManufacturingPlant`, `ProductionShop`, `ProductionPlan`, `ProductionOrder` |
| `ProcessPlanLayer.py` | `Part`, `Tool`, `Equipment`, `Operation`, `Supplier` |
| `ProductionProcessLayer.py` | `ProductionProcess`, `OperationalTask`, `Vehicle`, `Personnel`, `PartInstance` |
| `newDigitalThreadLayer.py` | `Specification` (base), `Version` (base), `State` (base) and all sub-classes |
| `newEventLayer.py` | `ChangeSet`, `ChangeAction`, `EffectivityScope` |

---

## Prerequisites

| Requirement | Version |
|-------------|---------|
| Python | 3.10+ |
| Neo4j Community Edition | 4.x (recommended 4.4) |
| APOC plugin | matching Neo4j version |
| OpenAI API key | GPT-4o access |

---

## 1 — Install Neo4j

### Option A — Neo4j Desktop (Windows / Mac)
1. Download from [neo4j.com/download](https://neo4j.com/download/).
2. Create a new **Local DBMS**, set your password.
3. Install the **APOC** plugin from the plugin panel before starting the database.
4. Start the database.

### Option B — Docker
```bash
docker run \
  --name autoam-neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/<your_password> \
  -e NEO4JPLUGINS='["apoc"]' \
  neo4j:4.4-community
```

### Verify APOC is available
Open Neo4j Browser at `http://localhost:7474` and run:
```cypher
RETURN apoc.version();
```
If this fails, the agent's schema injection service (`services/kg_schema_service.py`) will not work — install APOC before proceeding.

---

## 2 — Configure Neo4j credentials

The application reads credentials from environment variables.

```bash
cp .env.example .env
```

Edit `.env`:
```
NEO4J_BOLT=bolt://neo4j:<your_password>@localhost:7687
OPENAI_API_KEY=sk-...
```

> The default username for Neo4j is `neo4j`. If you changed it, update the bolt URL accordingly:
> `bolt://<username>:<password>@localhost:7687`

---

## 3 — Create Neo4j constraints & indexes

Run the provided Cypher script against your database **once** before loading any data.

**Option A — Neo4j Browser**

Paste the contents of `setup_neo4j_constraints.cypher` into the Browser query editor and execute.

**Option B — cypher-shell**
```bash
cypher-shell -u neo4j -p <your_password> < setup_neo4j_constraints.cypher
```

**Option C — Python (after installing dependencies)**
```python
from neo4j import GraphDatabase

driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "<your_password>"))
with driver.session() as session:
    with open("setup_neo4j_constraints.cypher") as f:
        for statement in f.read().split(";"):
            s = statement.strip()
            if s and not s.startswith("//"):
                session.run(s)
driver.close()
```

---

## 4 — Align your dataset with the schema

The graph schema is defined by the neomodel classes in the domain layer files. When loading your own data, each node and relationship **must** match these definitions.

### Node label rules

Every node label must match a class name exactly (case-sensitive):

```
VehicleFamily · VehicleVariant · ProductDocument
ManufacturingPlant · ProductionShop · ProductionPlan · ProductionOrder
Part · Tool · Equipment · Operation · Supplier
Vehicle · Personnel · ProductionProcess · OperationalTask
PartInstance · PartBatch · PartSerial
ToolInstance · ManualToolInstance · PrecisionToolInstance
EquipmentInstance · RoboticEquipmentInstance · ProcessEquipmentInstance
  DiagnosticEquipmentInstance · MaterialHandlingEquipmentInstance
Specification · VehicleVariantSpecification · PartSpecification
  ToolSpecification · ManualToolSpecification · PrecisionToolSpecification
  EquipmentSpecification · RoboticEquipmentSpecification
  ProcessEquipmentSpecification · DiagnosticEquipmentSpecification
  MaterialHandlingEquipmentSpecification
Version · ProductDocumentVersion · OperationVersion
  ProductionPlanVersion · ProductionOrderVersion
State · ProductionProcessState · PersonnelState · EquipmentState
ChangeSet · ChangeAction · EffectivityScope
```

### Required properties

| Node | Required properties |
|------|-------------------|
| `Part`, `Tool`, `Equipment`, `Operation` | `identifier` (unique), `name`, `current_status` |
| `Vehicle` | `identifier` |
| `ProductionPlan`, `ProductionOrder` | `identifier`, `current_version`, `current_status` |
| `Specification` subclasses | `identifier` (unique), `status` |
| `Version` subclasses | `identifier` (unique), `version`, `status` |
| `State` subclasses | `identifier` (unique), `status`, `validFrom` |
| `ChangeSet` | `identifier` (unique), `title` |
| `ChangeAction` | `identifier` (unique), `actionType` |

### Date format

All datetime properties must be stored as strings in this exact format:
```
'YYYY-MM-DD HH:MM:SS'
```
Example: `'2024-03-15 08:30:00'`

### Key relationship types

```
(VehicleFamily)-[:HAS_VARIANT]->(VehicleVariant)
(VehicleVariant)-[:CURRENT_SPECIFICATION]->(VehicleVariantSpecification)
(ProductionPlan)-[:CURRENT_VERSION]->(ProductionPlanVersion)
(ProductionOrder)-[:CURRENT_VERSION]->(ProductionOrderVersion)
(ProductionOrderVersion)-[:INSTANTIATES_PLAN]->(ProductionPlanVersion)
(ProductionProcess)-[:REALIZES_PLAN]->(ProductionPlanVersion)
(ProductionProcess)-[:PRODUCES_VEHICLE]->(Vehicle)
(ProductionProcess)-[:HAS_TASK]->(OperationalTask)
(OperationalTask)-[:HAS_PARTICIPANT]->(Personnel)
(OperationalTask)-[:USE_EQUIPMENT]->(EquipmentInstance)
(OperationalTask)-[:USE_TOOL]->(ToolInstance)
(OperationalTask)-[:CONSUMES_PART]->(PartInstance)
(OperationalTask)-[:INSTANTIATES_OPERATION]->(OperationVersion)
(ManufacturingPlant)-[:CREATES_PLAN]->(ProductionPlan)
(ProductionOrder)-[:ASSIGNED_TO]->(ManufacturingPlant)
(Part)-[:CURRENT_SPECIFICATION]->(PartSpecification)
(Equipment)-[:CURRENT_SPECIFICATION]->(EquipmentSpecification)
(VehicleVariantSpecification)-[:HAS_BOMITEM]->(PartSpecification)
```

### Minimum working graph for the agent

To get meaningful answers from the agent, your graph should include at minimum:

1. **At least one** `VehicleFamily` → `VehicleVariant` chain
2. **At least one** `ProductionPlan` → `ProductionPlanVersion`
3. **At least one** `ProductionOrder` → `ProductionOrderVersion` → (INSTANTIATES_PLAN) → `ProductionPlanVersion`
4. **At least one** `ProductionProcess` → (REALIZES_PLAN) → `ProductionPlanVersion` and (PRODUCES_VEHICLE) → `Vehicle`
5. `ManufacturingPlant` → (CREATES_PLAN) → `ProductionPlan`

---

## 5 — Python setup

```bash
# Clone the repo
git clone <repo-url>
cd AUTOAM-release

# Create and activate a virtual environment
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

---

## 6 — Run the application

```bash
streamlit run app.py
```

Open your browser at `http://localhost:8501`.

On first run the sidebar will show **Neo4j: connected** if credentials are correct. If you see an error, check your `.env` values and that Neo4j is running.

---

## Project structure

```
AUTOAM-release/
├── app.py                        # Streamlit entry point
├── config.py                     # Env-based configuration
├── requirements.txt
├── setup_neo4j_constraints.cypher
├── .env.example
│
├── ProductDesignLayer.py         ┐
├── PlantOrganizationLayer.py     │
├── ProcessPlanLayer.py           │  Domain layer files — DO NOT MODIFY
├── ProductionProcessLayer.py     │
├── newDigitalThreadLayer.py      │
├── newEventLayer.py              ┘
│
├── agent/
│   ├── agent.py                  # Main HITL agent pipeline
│   ├── ner.py                    # Named entity recognition
│   ├── query_planner.py          # Scenario routing
│   ├── graph_primitives.py       # Deterministic Cypher templates
│   ├── tools.py                  # OpenAI function tool definitions
│   ├── intent_classifier.py
│   └── context_manager.py
│
├── services/
│   ├── neo4j_service.py          # DB connection + safe_run
│   ├── spec_update_service.py    # Versioned spec updates + ChangeSet
│   ├── impact_analysis_service.py
│   ├── template_service.py       # RetrievalTemplate CRUD
│   ├── schema_service.py         # SchemaNode management
│   ├── memory_service.py         # Session memory (Tier 1/2/3)
│   └── kg_schema_service.py      # BFS schema injection for agent
│
├── schema/
│   └── schema_models.py          # SchemaNode, SchemaProperty, SchemaRelationship
│
├── ui/
│   ├── agent_page.py             # Conversational agent UI
│   ├── template_page.py          # Query template catalog
│   └── cypher_page.py            # Raw Cypher console
│
└── utils/
    ├── graph_utils.py
    ├── neo4j_conn.py
    ├── neo4j_schema.py
    └── utilities.py
```

---

## Test Dataset

The `data/test_dataset.json` file contains **over 100 test queries** covering various complexity levels and scenario types for testing the agent's capabilities:

- **Level 1 (L1)**: Single entity queries — basic retrieval of nodes with and without filters
- **Level 2 (L2)**: Relational queries — multi-hop graph traversals and filtered relationships  
- **Level 3 (L3)**: Complex queries — chains, AND/OR logic, independent queries, and mixed scenarios

### Dataset structure

Each test case includes:
- `id`: Unique identifier (e.g., `L1-001`, `L2-015`, `L3-045`)
- `level`: Query complexity level (1, 2, or 3)
- `complexity`: Query pattern type (e.g., `single_entity`, `relational_direct`, `chain`, `and`, `or`)
- `question`: Natural language question in English
- `cypher`: Corresponding Cypher query template

### Anonymized identifiers

All sensitive data (vehicle IDs, part codes, personnel names, supplier IDs, etc.) have been replaced with anonymized placeholders:
- Vehicle identifiers → `@vehicleXXX`
- Part codes → `@partXXX`
- Personnel → `@personnelXXX`
- Suppliers → `@supplierXXX`
- Manufacturing plants → `@productionshopXXX`
- Production orders → `@productionorderXXX`
- And other entity types similarly anonymized

---

## Environment variables reference

| Variable | Default | Description |
|----------|---------|-------------|
| `NEO4J_BOLT` | `bolt://neo4j:12345678@localhost:7687` | Neo4j bolt connection string |
| `OPENAI_API_KEY` | _(required)_ | OpenAI API key |
| `OPENAI_MODEL` | `gpt-4o` | OpenAI model name |

---

## Troubleshooting

**Neo4j connection fails**
- Confirm Neo4j is running and the bolt port (7687) is accessible.
- Verify credentials in `.env` match your Neo4j password.
- On first launch, Neo4j requires you to change the default password (`neo4j`) before allowing connections.

**APOC not found**
- `kg_schema_service.py` calls `apoc.meta.data()` to introspect the graph schema.
- Install the APOC plugin matching your Neo4j version and restart the database.

**`neomodel` constraint errors on startup**
- Run `setup_neo4j_constraints.cypher` first; neomodel expects unique indexes to exist.

**Agent returns "Please provide more specific details"**
- The NER step found no entities. Try naming entities explicitly, e.g. "Show me vehicles in ProductionPlan PL011015".

---

## Critical architecture rules

1. `Specification` and `State` classes in `newDigitalThreadLayer.py` are **immutable** — never modify their properties or relationships.
2. All spec updates must auto-create a `ChangeSet` + `ChangeAction` (digital thread) via `spec_update_service`.
3. Every schema change must also create a `ChangeSet` with `changeType="SCHEMA"`.
4. Routing uses NER output from the **rewritten** question — clicked entity context is used only for question rewriting, not for direct routing.
