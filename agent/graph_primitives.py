"""
Graph Primitives — deterministic Cypher templates keyed by "{LabelA}_to_{LabelB}".
Each template uses verified relationship names from the domain layer source code.

Lookup is done by building the key directly from NER-extracted label pairs —
no separate mapping dict needed. Adding a new entry here automatically makes it
discoverable by plan_query().

Custom primitives added via the UI are stored in Neo4j as RetrievalTemplate
nodes with category="primitive" and merged in at runtime via load_custom_primitives().
"""
from __future__ import annotations

GRAPH_PRIMITIVES: dict[str, str] = {
    # ── Vehicle_to_ ───────────────────────────────────────────────────────────
    "Vehicle_to_Part": (
        "MATCH (v:Vehicle {identifier: $a_id})"
        "-[:CONFIGURED_TO]->(vvs:VehicleVariantSpecification)"
        "-[:HAS_BOMITEM]->(ps:PartSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(p:Part) "
        "RETURN v AS Vehicle, p AS Part"
    ),
    "Vehicle_to_VehicleVariant": (
        "MATCH (v:Vehicle {identifier: $a_id})"
        "-[:CONFIGURED_TO]->(vvs:VehicleVariantSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(vv:VehicleVariant) "
        "RETURN v AS Vehicle, vv AS VehicleVariant"
    ),
    "Vehicle_to_VehicleFamily": (
        "MATCH (v:Vehicle {identifier: $a_id})"
        "-[:CONFIGURED_TO]->(vvs:VehicleVariantSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(:VehicleVariant)"
        "<-[:HAS_VARIANT]-(vf:VehicleFamily) "
        "RETURN v AS Vehicle, vf AS VehicleFamily"
    ),
    "Vehicle_to_Supplier": (
        "MATCH (v:Vehicle {identifier: $a_id})"
        "<-[:PRODUCES_VEHICLE]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:CONSUMES_PART]->(:PartInstance)"
        "-[:SUPPLIED_BY]->(s:Supplier) "
        "RETURN v AS Vehicle, s AS Supplier"
    ),
    "Vehicle_to_ProductionProcess": (
        "MATCH (v:Vehicle {identifier: $a_id})"
        "<-[:PRODUCES_VEHICLE]-(p:ProductionProcess) "
        "RETURN v AS Vehicle, p AS ProductionProcess"
    ),
    "Vehicle_to_PartBatch": (
        "MATCH (v:Vehicle {identifier: $a_id})"
        "<-[:PRODUCES_VEHICLE]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:CONSUMES_PART]->(b:PartBatch) "
        "RETURN v AS Vehicle, b AS PartBatch"
    ),
    "Vehicle_to_Personnel": (
        "MATCH (v:Vehicle {identifier: $a_id})"
        "<-[:PRODUCES_VEHICLE]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:HAS_PARTICIPANT]->(p:Personnel) "
        "RETURN v AS Vehicle, p AS Personnel"
    ),
    "Vehicle_to_EquipmentInstance": (
        "MATCH (v:Vehicle {identifier: $a_id})"
        "<-[:PRODUCES_VEHICLE]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:USE_EQUIPMENT]->(e:EquipmentInstance) "
        "RETURN v AS Vehicle, e AS EquipmentInstance"
    ),
    "Vehicle_to_ToolInstance": (
        "MATCH (v:Vehicle {identifier: $a_id})"
        "<-[:PRODUCES_VEHICLE]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:USE_TOOL]->(t:ToolInstance) "
        "RETURN v AS Vehicle, t AS ToolInstance"
    ),
    "Vehicle_to_ProductionOrder": (
        "MATCH (v:Vehicle {identifier: $a_id})"
        "<-[:PRODUCES_VEHICLE]-(pp:ProductionProcess)"
        "-[:REALIZES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:INSTANTIATES_PLAN]-(pov:ProductionOrderVersion)"
        "<-[:CURRENT_VERSION]-(p:ProductionOrder) "
        "RETURN v AS Vehicle, p AS ProductionOrder"
    ),
    "Vehicle_to_ManufacturingPlant": (
        "MATCH (v:Vehicle {identifier: $a_id})"
        "<-[:PRODUCES_VEHICLE]-(pp:ProductionProcess)"
        "-[:REALIZES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:INSTANTIATES_PLAN]-(pov:ProductionOrderVersion)"
        "<-[:CURRENT_VERSION]-(:ProductionOrder)"
        "-[:ASSIGNED_TO]->(m:ManufacturingPlant) "
        "RETURN v AS Vehicle, m AS ManufacturingPlant"
    ),
    "Vehicle_to_AssemblyShop": (
        "MATCH (v:Vehicle {identifier: $a_id})"
        "<-[:PRODUCES_VEHICLE]-(pp:ProductionProcess)"
        "-[:OCCURS_AT]->(a:AssemblyShop) "
        "RETURN v AS Vehicle, a AS AssemblyShop"
    ),
    "Vehicle_to_ProductionPlan": (
        "MATCH (v:Vehicle {identifier: $a_id})"
        "<-[:PRODUCES_VEHICLE]-(pp:ProductionProcess)"
        "-[:REALIZES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:CURRENT_VERSION]-(p:ProductionPlan) "
        "RETURN v AS Vehicle, p AS ProductionPlan"
    ),
    "Vehicle_to_ProductionShop": (
        "MATCH (v:Vehicle {identifier: $a_id})"
        "<-[:PRODUCES_VEHICLE]-(pp:ProductionProcess)"
        "-[:REALIZES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:INSTANTIATES_PLAN]-(pov:ProductionOrderVersion)"
        "<-[:CURRENT_VERSION]-(:ProductionOrder)"
        "-[:ASSIGNED_TO]->(:ManufacturingPlant)"
        "-[:HAS_SHOP]->(p:ProductionShop) "
        "RETURN v AS Vehicle, p AS ProductionShop"
    ),
    "Vehicle_to_ProductDocument": (
        "MATCH (v:Vehicle {identifier: $a_id})"
        "-[:CONFIGURED_TO]->(vvs:VehicleVariantSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(:VehicleVariant)"
        "<-[:HAS_VARIANT]-(:VehicleFamily)"
        "-[:DESCRIBED_IN]->(p:ProductDocument) "
        "RETURN v AS Vehicle, p AS ProductDocument"
    ),
    "Vehicle_to_Operation": (
        "MATCH (v:Vehicle {identifier: $a_id})"
        "<-[:PRODUCES_VEHICLE]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:INSTANTIATES_OPERATION]->(ov:OperationVersion)"
        "<-[:CURRENT_VERSION]-(o:Operation) "
        "RETURN v AS Vehicle, o AS Operation"
    ),
    # "Vehicle_to_WorkStep": (
    #     "MATCH (v:Vehicle {identifier: $a_id})"
    #     "<-[:PRODUCES_VEHICLE]-(pp:ProductionProcess)"
    #     "-[:HAS_TASK]->(task:OperationalTask)"
    #     "-[:INSTANTIATES_OPERATION]->(ov:OperationVersion)"
    #     "-[:HAS_STEP]->(wsv:WorkStepVersion)"
    #     "<-[:CURRENT_VERSION]-(w:WorkStep) "
    #     "RETURN v AS Vehicle, w AS WorkStep"
    # ),
    "Vehicle_to_OperationalTask": (
        "MATCH (v:Vehicle {identifier: $a_id})"
        "<-[:PRODUCES_VEHICLE]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(o:OperationalTask) "
        "RETURN v AS Vehicle, o AS OperationalTask"
    ),

    # ── Operation_to_ ─────────────────────────────────────────────────────────
    "Operation_to_ProductionShop": (
        "MATCH (o:Operation {identifier: $a_id})"
        "-[:QUALIFIED_FOR]->(p:ProductionShop) "
        "RETURN o AS Operation, p AS ProductionShop"
    ),
    "Operation_to_ManufacturingPlant": (
        "MATCH (o:Operation {identifier: $a_id})"
        "-[:QUALIFIED_FOR]->(:AssemblyShop)"
        "<-[:HAS_SHOP]-(m:ManufacturingPlant) "
        "RETURN o AS Operation, m AS ManufacturingPlant"
    ),
    # "Operation_to_WorkStep": (
    #     "MATCH (o:Operation {identifier: $a_id})"
    #     "-[:CURRENT_VERSION]->(ov:OperationVersion)"
    #     "-[:HAS_STEP]->(wsv:WorkStepVersion)"
    #     "<-[:CURRENT_VERSION]-(w:WorkStep) "
    #     "RETURN o AS Operation, w AS WorkStep"
    # ),
    "Operation_to_Part": (
        "MATCH (o:Operation {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(ov:OperationVersion)"
        "-[:REQUIRES_PART]->(ps:PartSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(p:Part) "
        "RETURN o AS Operation, p AS Part"
    ),
    "Operation_to_Tool": (
        "MATCH (o:Operation {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(ov:OperationVersion)"
        "-[:REQUIRES_TOOL]->(ts:ToolSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(t:Tool) "
        "RETURN o AS Operation, t AS Tool"
    ),
    "Operation_to_ManualTool": (
        "MATCH (o:Operation {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(ov:OperationVersion)"
        "-[:REQUIRES_TOOL]->(mts:ManualToolSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(m:ManualTool) "
        "RETURN o AS Operation, m AS ManualTool"
    ),
    "Operation_to_PrecisionTool": (
        "MATCH (o:Operation {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(ov:OperationVersion)"
        "-[:REQUIRES_TOOL]->(pts:PrecisionToolSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(p:PrecisionTool) "
        "RETURN o AS Operation, p AS PrecisionTool"
    ),
    "Operation_to_Equipment": (
        "MATCH (o:Operation {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(ov:OperationVersion)"
        "-[:REQUIRES_EQUIPMENT]->(es:EquipmentSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(p:Equipment) "
        "RETURN o AS Operation, p AS Equipment"
    ),

    "Operation_to_EquipmentInstance": (
        "MATCH (o:Operation {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(ov:OperationVersion)"
        "-[:REQUIRES_EQUIPMENT]->(es:EquipmentSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(p:Equipment)<-[:INSTANCE_OF]-(ei:EquipmentInstance) "
        "RETURN o AS Operation, ei AS EquipmentInstance"
    ),

    "EquipmentInstance_to_Operation": (
        "MATCH (o:Operation)"
        "-[:CURRENT_VERSION]->(ov:OperationVersion)"
        "-[:REQUIRES_EQUIPMENT]->(es:EquipmentSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(p:Equipment)<-[:INSTANCE_OF]-(ei:EquipmentInstance {identifier: $a_id}) "
        "RETURN o AS Operation, ei AS EquipmentInstance"
    ),

    "Operation_to_RoboticEquipment": (
        "MATCH (o:Operation {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(ov:OperationVersion)"
        "-[:REQUIRES_EQUIPMENT]->(res:RoboticEquipmentSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(p:RoboticEquipment) "
        "RETURN o AS Operation, p AS RoboticEquipment"
    ),
    "Operation_to_ProcessEquipment": (
        "MATCH (o:Operation {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(ov:OperationVersion)"
        "-[:REQUIRES_EQUIPMENT]->(pes:ProcessEquipmentSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(p:ProcessEquipment) "
        "RETURN o AS Operation, p AS ProcessEquipment"
    ),
    "Operation_to_DiagnosticEquipment": (
        "MATCH (o:Operation {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(ov:OperationVersion)"
        "-[:REQUIRES_EQUIPMENT]->(des:DiagnosticEquipmentSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(p:DiagnosticEquipment) "
        "RETURN o AS Operation, p AS DiagnosticEquipment"
    ),
    "Operation_to_MaterialHandlingEquipment": (
        "MATCH (o:Operation {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(ov:OperationVersion)"
        "-[:REQUIRES_EQUIPMENT]->(mhes:MaterialHandlingEquipmentSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(p:MaterialHandlingEquipment) "
        "RETURN o AS Operation, p AS MaterialHandlingEquipment"
    ),
    "Operation_to_Supplier": (
        "MATCH (o:Operation {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(ov:OperationVersion)"
        "-[:REQUIRES_PART]->(ps:PartSpecification)"
        "-[:HAS_SUPPLIER]->(s:Supplier) "
        "RETURN o AS Operation, s AS Supplier"
    ),
    "Supplier_to_Operation": (
        "MATCH (o:Operation)"
        "-[:CURRENT_VERSION]->(ov:OperationVersion)"
        "-[:REQUIRES_PART]->(ps:PartSpecification)"
        "-[:HAS_SUPPLIER]->(s:Supplier {identifier: $a_id}) "
        "RETURN o AS Operation, s AS Supplier"
    ),
    "Operation_to_ProductDocument": (
        "MATCH (o:Operation {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(ov:OperationVersion)"
        "-[:DERIVED_FROM]->(pdv:ProductDocumentVersion)"
        "<-[:CURRENT_VERSION]-(p:ProductDocument) "
        "RETURN o AS Operation, p AS ProductDocument"
    ),
    "Operation_to_VehicleFamily": (
        "MATCH (o:Operation {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(ov:OperationVersion)"
        "-[:DERIVED_FROM]->(pdv:ProductDocumentVersion)"
        "<-[:CURRENT_VERSION]-(:ProductDocument)"
        "<-[:DESCRIBED_IN]-(v:VehicleFamily) "
        "RETURN o AS Operation, v AS VehicleFamily"
    ),
    "Operation_to_VehicleVariant": (
        "MATCH (o:Operation {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(ov:OperationVersion)"
        "-[:DERIVED_FROM]->(pdv:ProductDocumentVersion)"
        "<-[:CURRENT_VERSION]-(:ProductDocument)"
        "<-[:DESCRIBED_IN]-(:VehicleFamily)"
        "-[:HAS_VARIANT]->(v:VehicleVariant) "
        "RETURN o AS Operation, v AS VehicleVariant"
    ),
    "Operation_to_OperationalTask": (
        "MATCH (o:Operation {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(ov:OperationVersion)"
        "<-[:INSTANTIATES_OPERATION]-(ot:OperationalTask) "
        "RETURN o AS Operation, ot AS OperationalTask"
    ),
    "Operation_to_ProductionProcess": (
        "MATCH (o:Operation {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(ov:OperationVersion)"
        "<-[:INSTANTIATES_OPERATION]-(task:OperationalTask)"
        "<-[:HAS_TASK]-(p:ProductionProcess) "
        "RETURN o AS Operation, p AS ProductionProcess"
    ),
    "Operation_to_Vehicle": (
        "MATCH (o:Operation {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(ov:OperationVersion)"
        "<-[:INSTANTIATES_OPERATION]-(task:OperationalTask)"
        "<-[:HAS_TASK]-(pp:ProductionProcess)"
        "-[:PRODUCES_VEHICLE]->(v:Vehicle) "
        "RETURN o AS Operation, v AS Vehicle"
    ),
    "Operation_to_ProductionPlan": (
        "MATCH (o:Operation {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(ov:OperationVersion)"
        "<-[:INSTANTIATES_OPERATION]-(task:OperationalTask)"
        "<-[:HAS_TASK]-(pp:ProductionProcess)"
        "-[:REALIZES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:CURRENT_VERSION]-(p:ProductionPlan) "
        "RETURN o AS Operation, p AS ProductionPlan"
    ),
    "Operation_to_ProductionOrder": (
        "MATCH (o:Operation {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(ov:OperationVersion)"
        "<-[:INSTANTIATES_OPERATION]-(task:OperationalTask)"
        "<-[:HAS_TASK]-(pp:ProductionProcess)"
        "-[:REALIZES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:INSTANTIATES_PLAN]-(pov:ProductionOrderVersion)"
        "<-[:CURRENT_VERSION]-(p:ProductionOrder) "
        "RETURN o AS Operation, p AS ProductionOrder"
    ),

    # ── ManufacturingPlant_to_ ────────────────────────────────────────────────
    "ManufacturingPlant_to_VehicleVariant": (
        "MATCH (o:ManufacturingPlant {identifier: $a_id})"
        "-[:HAS_SHOP]->(:AssemblyShop)"
        "-[:QUALIFIED_PRODUCE]->(v:VehicleVariant) "
        "RETURN o AS ManufacturingPlant, v AS VehicleVariant"
    ),
    "ManufacturingPlant_to_VehicleFamily": (
        "MATCH (o:ManufacturingPlant {identifier: $a_id})"
        "-[:HAS_SHOP]->(:AssemblyShop)"
        "-[:QUALIFIED_PRODUCE]->(:VehicleVariant)"
        "<-[:HAS_VARIANT]-(v:VehicleFamily) "
        "RETURN o AS ManufacturingPlant, v AS VehicleFamily"
    ),
    "ManufacturingPlant_to_Operation": (
        "MATCH (m:ManufacturingPlant {identifier: $a_id})"
        "-[:HAS_SHOP]->(:ProductionShop)"
        "<-[:QUALIFIED_FOR]-(o:Operation) "
        "RETURN o AS Operation, m AS ManufacturingPlant"
    ),
    "ManufacturingPlant_to_ProductionShop": (
        "MATCH (o:ManufacturingPlant {identifier: $a_id})"
        "-[:HAS_SHOP]->(a:ProductionShop) "
        "RETURN o AS ManufacturingPlant, a AS ProductionShop"
    ),
        "ManufacturingPlant_to_AssemblyShop": (
        "MATCH (o:ManufacturingPlant {identifier: $a_id})"
        "-[:HAS_SHOP]->(a:AssemblyShop) "
        "RETURN o AS ManufacturingPlant, a AS AssemblyShop"
    ),
    "ManufacturingPlant_to_ProductionOrder": (
        "MATCH (o:ManufacturingPlant {identifier: $a_id})"
        "<-[:ASSIGNED_TO]-(p:ProductionOrder) "
        "RETURN o AS ManufacturingPlant, p AS ProductionOrder"
    ),
    "ManufacturingPlant_to_ProductionPlan": (
        "MATCH (o:ManufacturingPlant {identifier: $a_id})"
        "<-[:ASSIGNED_TO]-(:ProductionOrder)"
        "-[:CURRENT_VERSION]->(pov:ProductionOrderVersion)"
        "-[:INSTANTIATES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:CURRENT_VERSION]-(p:ProductionPlan) "
        "RETURN o AS ManufacturingPlant, p AS ProductionPlan"
    ),
    "ManufacturingPlant_to_ProductionProcess": (
        "MATCH (o:ManufacturingPlant {identifier: $a_id})"
        "<-[:ASSIGNED_TO]-(:ProductionOrder)"
        "-[:CURRENT_VERSION]->(pov:ProductionOrderVersion)"
        "-[:INSTANTIATES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:REALIZES_PLAN]-(p:ProductionProcess) "
        "RETURN o AS ManufacturingPlant, p AS ProductionProcess"
    ),
    "ManufacturingPlant_to_OperationalTask": (
        "MATCH (o:ManufacturingPlant {identifier: $a_id})"
        "<-[:ASSIGNED_TO]-(:ProductionOrder)"
        "-[:CURRENT_VERSION]->(pov:ProductionOrderVersion)"
        "-[:INSTANTIATES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:REALIZES_PLAN]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(ot:OperationalTask) "
        "RETURN o AS ManufacturingPlant, ot AS OperationalTask"
    ),
    "ManufacturingPlant_to_Vehicle": (
        "MATCH (o:ManufacturingPlant {identifier: $a_id})"
        "<-[:ASSIGNED_TO]-(:ProductionOrder)"
        "-[:CURRENT_VERSION]->(pov:ProductionOrderVersion)"
        "-[:INSTANTIATES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:REALIZES_PLAN]-(pp:ProductionProcess)"
        "-[:PRODUCES_VEHICLE]->(v:Vehicle) "
        "RETURN o AS ManufacturingPlant, v AS Vehicle"
    ),
    "ManufacturingPlant_to_Part": (
        "MATCH (o:ManufacturingPlant {identifier: $a_id})"
        "-[:HAS_SHOP]->(:AssemblyShop)"
        "<-[:QUALIFIED_FOR]-(:Operation)"
        "-[:CURRENT_VERSION]->(ov:OperationVersion)"
        "-[:REQUIRES_PART]->(ps:PartSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(p:Part) "
        "RETURN o AS ManufacturingPlant, p AS Part"
    ),
    "ManufacturingPlant_to_Equipment": (
        "MATCH (o:ManufacturingPlant {identifier: $a_id})"
        "-[:HAS_SHOP]->(:AssemblyShop)"
        "<-[:QUALIFIED_FOR]-(:Operation)"
        "-[:CURRENT_VERSION]->(ov:OperationVersion)"
        "-[:REQUIRES_EQUIPMENT]->(es:EquipmentSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(e:Equipment) "
        "RETURN o AS ManufacturingPlant, e AS Equipment"
    ),
    "ManufacturingPlant_to_Tool": (
        "MATCH (o:ManufacturingPlant {identifier: $a_id})"
        "-[:HAS_SHOP]->(:AssemblyShop)"
        "<-[:QUALIFIED_FOR]-(:Operation)"
        "-[:CURRENT_VERSION]->(ov:OperationVersion)"
        "-[:REQUIRES_TOOL]->(ts:ToolSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(t:Tool) "
        "RETURN o AS ManufacturingPlant, t AS Tool"
    ),
    "ManufacturingPlant_to_PartInstance": (
        "MATCH (o:ManufacturingPlant {identifier: $a_id})"
        "<-[:ASSIGNED_TO]-(:ProductionOrder)"
        "-[:CURRENT_VERSION]->(pov:ProductionOrderVersion)"
        "-[:INSTANTIATES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:REALIZES_PLAN]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:CONSUMES_PART]->(p:PartInstance) "
        "RETURN o AS ManufacturingPlant, p AS PartInstance"
    ),
    "ManufacturingPlant_to_PartBatch": (
        "MATCH (o:ManufacturingPlant {identifier: $a_id})"
        "<-[:ASSIGNED_TO]-(:ProductionOrder)"
        "-[:CURRENT_VERSION]->(pov:ProductionOrderVersion)"
        "-[:INSTANTIATES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:REALIZES_PLAN]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:CONSUMES_PART]->(p:PartBatch) "
        "RETURN o AS ManufacturingPlant, p AS PartBatch"
    ),
    "PartBatch_to_ManufacturingPlant": (
        "MATCH (o:ManufacturingPlant)"
        "<-[:ASSIGNED_TO]-(:ProductionOrder)"
        "-[:CURRENT_VERSION]->(pov:ProductionOrderVersion)"
        "-[:INSTANTIATES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:REALIZES_PLAN]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:CONSUMES_PART]->(p:PartBatch {batchNumber: $a_id}) "
        "RETURN o AS ManufacturingPlant, p AS PartBatch"
    ),
    "ManufacturingPlant_to_EquipmentInstance": (
        "MATCH (o:ManufacturingPlant {identifier: $a_id})"
        "<-[:ASSIGNED_TO]-(:ProductionOrder)"
        "-[:CURRENT_VERSION]->(pov:ProductionOrderVersion)"
        "-[:INSTANTIATES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:REALIZES_PLAN]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:USE_EQUIPMENT]->(e:EquipmentInstance) "
        "RETURN o AS ManufacturingPlant, e AS EquipmentInstance"
    ),
    "ManufacturingPlant_to_ToolInstance": (
        "MATCH (o:ManufacturingPlant {identifier: $a_id})"
        "<-[:ASSIGNED_TO]-(:ProductionOrder)"
        "-[:CURRENT_VERSION]->(pov:ProductionOrderVersion)"
        "-[:INSTANTIATES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:REALIZES_PLAN]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:USE_TOOL]->(t:ToolInstance) "
        "RETURN o AS ManufacturingPlant, t AS ToolInstance"
    ),
    "ManufacturingPlant_to_Personnel": (
        "MATCH (o:ManufacturingPlant {identifier: $a_id})"
        "<-[:ASSIGNED_TO]-(:ProductionOrder)"
        "-[:CURRENT_VERSION]->(pov:ProductionOrderVersion)"
        "-[:INSTANTIATES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:REALIZES_PLAN]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:HAS_PARTICIPANT]->(p:Personnel) "
        "RETURN o AS ManufacturingPlant, p AS Personnel"
    ),
    "ManufacturingPlant_to_Supplier": (
        "MATCH (o:ManufacturingPlant {identifier: $a_id})"
        "<-[:ASSIGNED_TO]-(:ProductionOrder)"
        "-[:CURRENT_VERSION]->(pov:ProductionOrderVersion)"
        "-[:INSTANTIATES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:REALIZES_PLAN]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:CONSUMES_PART]->(:PartInstance)"
        "-[:SUPPLIED_BY]->(s:Supplier) "
        "RETURN o AS ManufacturingPlant, s AS Supplier"
    ),

    # ── AssemblyShop_to_ ──────────────────────────────────────────────────────
    "AssemblyShop_to_VehicleVariant": (
        "MATCH (a:AssemblyShop {identifier: $a_id})"
        "-[:QUALIFIED_PRODUCE]->(v:VehicleVariant) "
        "RETURN a AS AssemblyShop, v AS VehicleVariant"
    ),
    "AssemblyShop_to_VehicleFamily": (
        "MATCH (a:AssemblyShop {identifier: $a_id})"
        "-[:QUALIFIED_PRODUCE]->(:VehicleVariant)"
        "<-[:HAS_VARIANT]-(v:VehicleFamily) "
        "RETURN a AS AssemblyShop, v AS VehicleFamily"
    ),
    "AssemblyShop_to_ProductionOrder": (
        "MATCH (a:AssemblyShop {identifier: $a_id})"
        "<-[:HAS_SHOP]-(:ManufacturingPlant)"
        "<-[:ASSIGNED_TO]-(p:ProductionOrder) "
        "RETURN a AS AssemblyShop, p AS ProductionOrder"
    ),
    "AssemblyShop_to_ProductionPlan": (
        "MATCH (a:AssemblyShop {identifier: $a_id})"
        "<-[:OCCURS_AT]-(pp:ProductionProcess)"
        "-[:REALIZES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:CURRENT_VERSION]-(p:ProductionPlan) "
        "RETURN a AS AssemblyShop, p AS ProductionPlan"
    ),
    "AssemblyShop_to_ProductionProcess": (
        "MATCH (a:AssemblyShop {identifier: $a_id})"
        "<-[:OCCURS_AT]-(p:ProductionProcess) "
        "RETURN a AS AssemblyShop, p AS ProductionProcess"
    ),
    "AssemblyShop_to_Vehicle": (
        "MATCH (a:AssemblyShop {identifier: $a_id})"
        "<-[:OCCURS_AT]-(p:ProductionProcess)"
        "-[:PRODUCES_VEHICLE]->(v:Vehicle) "
        "RETURN a AS AssemblyShop, v AS Vehicle"
    ),
    "AssemblyShop_to_ManufacturingPlant": (
        "MATCH (a:AssemblyShop {identifier: $a_id})"
        "<-[:HAS_SHOP]-(m:ManufacturingPlant) "
        "RETURN a AS AssemblyShop, m AS ManufacturingPlant"
    ),
    "AssemblyShop_to_Part": (
        "MATCH (a:AssemblyShop {identifier: $a_id})"
        "<-[:QUALIFIED_FOR]-(:Operation)"
        "-[:CURRENT_VERSION]->(ov:OperationVersion)"
        "-[:REQUIRES_PART]->(ps:PartSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(p:Part) "
        "RETURN a AS AssemblyShop, p AS Part"
    ),
    "AssemblyShop_to_Operation": (
        "MATCH (a:AssemblyShop {identifier: $a_id})"
        "<-[:QUALIFIED_FOR]-(o:Operation) "
        "RETURN a AS AssemblyShop, o AS Operation"
    ),
    "AssemblyShop_to_Equipment": (
        "MATCH (a:AssemblyShop {identifier: $a_id})"
        "<-[:QUALIFIED_FOR]-(:Operation)"
        "-[:CURRENT_VERSION]->(ov:OperationVersion)"
        "-[:REQUIRES_EQUIPMENT]->(es:EquipmentSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(e:Equipment) "
        "RETURN a AS AssemblyShop, e AS Equipment"
    ),
    "AssemblyShop_to_Tool": (
        "MATCH (a:AssemblyShop {identifier: $a_id})"
        "<-[:QUALIFIED_FOR]-(:Operation)"
        "-[:CURRENT_VERSION]->(ov:OperationVersion)"
        "-[:REQUIRES_TOOL]->(ts:ToolSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(t:Tool) "
        "RETURN a AS AssemblyShop, t AS Tool"
    ),
    "AssemblyShop_to_OperationalTask": (
        "MATCH (a:AssemblyShop {identifier: $a_id})"
        "<-[:OCCURS_AT]-(p:ProductionProcess)"
        "-[:HAS_TASK]->(o:OperationalTask) "
        "RETURN a AS AssemblyShop, o AS OperationalTask"
    ),
    "AssemblyShop_to_PartBatch": (
        "MATCH (a:AssemblyShop {identifier: $a_id})"
        "<-[:OCCURS_AT]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:CONSUMES_PART]->(p:PartBatch) "
        "RETURN a AS AssemblyShop, p AS PartBatch"
    ),
    "AssemblyShop_to_EquipmentInstance": (
        "MATCH (a:AssemblyShop {identifier: $a_id})"
        "<-[:OCCURS_AT]-(p:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:USE_EQUIPMENT]->(e:EquipmentInstance) "
        "RETURN a AS AssemblyShop, e AS EquipmentInstance"
    ),
    "AssemblyShop_to_ToolInstance": (
        "MATCH (a:AssemblyShop {identifier: $a_id})"
        "<-[:OCCURS_AT]-(p:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:USE_TOOL]->(t:ToolInstance) "
        "RETURN a AS AssemblyShop, t AS ToolInstance"
    ),
    "AssemblyShop_to_Personnel": (
        "MATCH (a:AssemblyShop {identifier: $a_id})"
        "<-[:OCCURS_AT]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:HAS_PARTICIPANT]->(p:Personnel) "
        "RETURN a AS AssemblyShop, p AS Personnel"
    ),
    "AssemblyShop_to_Supplier": (
        "MATCH (a:AssemblyShop {identifier: $a_id})"
        "<-[:OCCURS_AT]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:CONSUMES_PART]->(:PartInstance)"
        "-[:SUPPLIED_BY]->(s:Supplier) "
        "RETURN a AS AssemblyShop, s AS Supplier"
    ),


    "ProductionShop_to_VehicleVariant": (
        "MATCH (a:ProductionShop {identifier: $a_id})"
        "-[:QUALIFIED_PRODUCE]->(v:VehicleVariant) "
        "RETURN a AS ProductionShop, v AS VehicleVariant"
    ),
    "ProductionShop_to_VehicleFamily": (
        "MATCH (a:ProductionShop {identifier: $a_id})"
        "-[:QUALIFIED_PRODUCE]->(:VehicleVariant)"
        "<-[:HAS_VARIANT]-(v:VehicleFamily) "
        "RETURN a AS ProductionShop, v AS VehicleFamily"
    ),
    "ProductionShop_to_ProductionOrder": (
        "MATCH (a:ProductionShop {identifier: $a_id})"
        "<-[:HAS_SHOP]-(:ManufacturingPlant)"
        "<-[:ASSIGNED_TO]-(p:ProductionOrder) "
        "RETURN a AS ProductionShop, p AS ProductionOrder"
    ),
    "ProductionShop_to_ProductionPlan": (
        "MATCH (a:ProductionShop {identifier: $a_id})"
        "<-[:OCCURS_AT]-(pp:ProductionProcess)"
        "-[:REALIZES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:CURRENT_VERSION]-(p:ProductionPlan) "
        "RETURN a AS ProductionShop, p AS ProductionPlan"
    ),
    "ProductionShop_to_ProductionProcess": (
        "MATCH (a:ProductionShop {identifier: $a_id})"
        "<-[:OCCURS_AT]-(p:ProductionProcess) "
        "RETURN a AS ProductionShop, p AS ProductionProcess"
    ),
    "ProductionShop_to_Vehicle": (
        "MATCH (a:ProductionShop {identifier: $a_id})"
        "<-[:OCCURS_AT]-(p:ProductionProcess)"
        "-[:PRODUCES_VEHICLE]->(v:Vehicle) "
        "RETURN a AS ProductionShop, v AS Vehicle"
    ),
    "ProductionShop_to_ManufacturingPlant": (
        "MATCH (a:ProductionShop {identifier: $a_id})"
        "<-[:HAS_SHOP]-(m:ManufacturingPlant) "
        "RETURN a AS ProductionShop, m AS ManufacturingPlant"
    ),
    "ProductionShop_to_Part": (
        "MATCH (a:ProductionShop {identifier: $a_id})"
        "<-[:QUALIFIED_FOR]-(:Operation)"
        "-[:CURRENT_VERSION]->(ov:OperationVersion)"
        "-[:REQUIRES_PART]->(ps:PartSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(p:Part) "
        "RETURN a AS ProductionShop, p AS Part"
    ),
    "ProductionShop_to_Operation": (
        "MATCH (a:ProductionShop {identifier: $a_id})"
        "<-[:QUALIFIED_FOR]-(o:Operation) "
        "RETURN a AS ProductionShop, o AS Operation"
    ),
    "ProductionShop_to_Equipment": (
        "MATCH (a:ProductionShop {identifier: $a_id})"
        "<-[:QUALIFIED_FOR]-(:Operation)"
        "-[:CURRENT_VERSION]->(ov:OperationVersion)"
        "-[:REQUIRES_EQUIPMENT]->(es:EquipmentSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(e:Equipment) "
        "RETURN a AS ProductionShop, e AS Equipment"
    ),
    "ProductionShop_to_Tool": (
        "MATCH (a:ProductionShop {identifier: $a_id})"
        "<-[:QUALIFIED_FOR]-(:Operation)"
        "-[:CURRENT_VERSION]->(ov:OperationVersion)"
        "-[:REQUIRES_TOOL]->(ts:ToolSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(t:Tool) "
        "RETURN a AS ProductionShop, t AS Tool"
    ),
    "ProductionShop_to_OperationalTask": (
        "MATCH (a:ProductionShop {identifier: $a_id})"
        "<-[:OCCURS_AT]-(p:ProductionProcess)"
        "-[:HAS_TASK]->(o:OperationalTask) "
        "RETURN a AS ProductionShop, o AS OperationalTask"
    ),
    "ProductionShop_to_PartBatch": (
        "MATCH (a:ProductionShop {identifier: $a_id})"
        "<-[:OCCURS_AT]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:CONSUMES_PART]->(p:PartBatch) "
        "RETURN a AS ProductionShop, p AS PartBatch"
    ),
    "ProductionShop_to_EquipmentInstance": (
        "MATCH (a:ProductionShop {identifier: $a_id})"
        "<-[:OCCURS_AT]-(p:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:USE_EQUIPMENT]->(e:EquipmentInstance) "
        "RETURN a AS ProductionShop, e AS EquipmentInstance"
    ),

    "EquipmentInstance_to_ProductionShop": (
        "MATCH (a:ProductionShop)"
        "<-[:OCCURS_AT]-(p:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:USE_EQUIPMENT]->(e:EquipmentInstance {identifier: $a_id}) "
        "RETURN a AS ProductionShop, e AS EquipmentInstance"
    ),

    "ProductionShop_to_ToolInstance": (
        "MATCH (a:ProductionShop {identifier: $a_id})"
        "<-[:OCCURS_AT]-(p:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:USE_TOOL]->(t:ToolInstance) "
        "RETURN a AS ProductionShop, t AS ToolInstance"
    ),
    "ProductionShop_to_Personnel": (
        "MATCH (a:ProductionShop {identifier: $a_id})"
        "<-[:OCCURS_AT]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:HAS_PARTICIPANT]->(p:Personnel) "
        "RETURN a AS ProductionShop, p AS Personnel"
    ),
    "ProductionShop_to_Supplier": (
        "MATCH (a:ProductionShop {identifier: $a_id})"
        "<-[:OCCURS_AT]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:CONSUMES_PART]->(:PartInstance)"
        "-[:SUPPLIED_BY]->(s:Supplier) "
        "RETURN a AS ProductionShop, s AS Supplier"
    ),


    # ── VehicleFamily_to_ ─────────────────────────────────────────────────────
    "VehicleFamily_to_VehicleVariant": (
        "MATCH (vf:VehicleFamily {identifier: $a_id})"
        "-[:HAS_VARIANT]->(vv:VehicleVariant) "
        "RETURN vf AS VehicleFamily, vv AS VehicleVariant"
    ),
    "VehicleFamily_to_ProductDocument": (
        "MATCH (v:VehicleFamily {identifier: $a_id})"
        "-[:DESCRIBED_IN]->(p:ProductDocument) "
        "RETURN v AS VehicleFamily, p AS ProductDocument"
    ),
    "VehicleFamily_to_Vehicle": (
        "MATCH (vf:VehicleFamily {identifier: $a_id})"
        "-[:HAS_VARIANT]->(:VehicleVariant)"
        "-[:CURRENT_SPECIFICATION]->(vvs:VehicleVariantSpecification)"
        "<-[:CONFIGURED_TO]-(v:Vehicle) "
        "RETURN vf AS VehicleFamily, v AS Vehicle"
    ),
    "VehicleFamily_to_Operation": (
        "MATCH (v:VehicleFamily {identifier: $a_id})"
        "-[:DESCRIBED_IN]->(:ProductDocument)"
        "-[:CURRENT_VERSION]->(pdv:ProductDocumentVersion)"
        "<-[:DERIVED_FROM]-(ov:OperationVersion)"
        "<-[:CURRENT_VERSION]-(o:Operation) "
        "RETURN v AS VehicleFamily, o AS Operation"
    ),
    "VehicleFamily_to_ManufacturingPlant": (
        "MATCH (v:VehicleFamily {identifier: $a_id})"
        "-[:HAS_VARIANT]->(:VehicleVariant)"
        "<-[:QUALIFIED_PRODUCE]-(:AssemblyShop)"
        "<-[:HAS_SHOP]-(m:ManufacturingPlant) "
        "RETURN m AS ManufacturingPlant, v AS VehicleFamily"
    ),
    "VehicleFamily_to_AssemblyShop": (
        "MATCH (v:VehicleFamily {identifier: $a_id})"
        "-[:HAS_VARIANT]->(:VehicleVariant)"
        "<-[:QUALIFIED_PRODUCE]-(a:AssemblyShop) "
        "RETURN a AS AssemblyShop, v AS VehicleFamily"
    ),

    # ── VehicleVariant_to_ ────────────────────────────────────────────────────
    "VehicleVariant_to_Vehicle": (
        "MATCH (vv:VehicleVariant {identifier: $a_id})"
        "-[:CURRENT_SPECIFICATION]->(vvs:VehicleVariantSpecification)"
        "<-[:CONFIGURED_TO]-(veh:Vehicle) "
        "RETURN vv AS VehicleVariant, veh AS Vehicle"
    ),
    "VehicleVariant_to_Operation": (
        "MATCH (vv:VehicleVariant {identifier: $a_id})"
        "<-[:HAS_VARIANT]-(:VehicleFamily)"
        "-[:DESCRIBED_IN]->(:ProductDocument)"
        "-[:CURRENT_VERSION]->(pdv:ProductDocumentVersion)"
        "<-[:DERIVED_FROM]-(ov:OperationVersion)"
        "<-[:CURRENT_VERSION]-(o:Operation) "
        "RETURN vv AS VehicleVariant, o AS Operation"
    ),
    "VehicleVariant_to_ManufacturingPlant": (
        "MATCH (vv:VehicleVariant {identifier: $a_id})"
        "<-[:QUALIFIED_PRODUCE]-(:AssemblyShop)"
        "<-[:HAS_SHOP]-(mp:ManufacturingPlant) "
        "RETURN vv AS VehicleVariant, mp AS ManufacturingPlant"
    ),
    "VehicleVariant_to_AssemblyShop": (
        "MATCH (vv:VehicleVariant {identifier: $a_id})"
        "<-[:QUALIFIED_PRODUCE]-(a:AssemblyShop) "
        "RETURN vv AS VehicleVariant, a AS AssemblyShop"
    ),
    "VehicleVariant_to_VehicleFamily": (
        "MATCH (vv:VehicleVariant {identifier: $a_id})"
        "<-[:HAS_VARIANT]-(vf:VehicleFamily) "
        "RETURN vv AS VehicleVariant, vf AS VehicleFamily"
    ),

    # ── ProductDocument_to_ ───────────────────────────────────────────────────
    # "ProductDocument_to_WorkStep": (
    #     "MATCH (p:ProductDocument {identifier: $a_id})"
    #     "-[:CURRENT_VERSION]->(:ProductDocumentVersion)"
    #     "<-[:DERIVED_FROM]-(wsv:WorkStepVersion)"
    #     "<-[:CURRENT_VERSION]-(w:WorkStep) "
    #     "RETURN p AS ProductDocument, w AS WorkStep"
    # ),
    "ProductDocument_to_Vehicle": (
        "MATCH (p:ProductDocument {identifier: $a_id})"
        "<-[:DESCRIBED_IN]-(:VehicleFamily)"
        "-[:HAS_VARIANT]->(:VehicleVariant)"
        "-[:CURRENT_SPECIFICATION]->(vvs:VehicleVariantSpecification)"
        "<-[:CONFIGURED_TO]-(v:Vehicle) "
        "RETURN v AS Vehicle, p AS ProductDocument"
    ),
    "ProductDocument_to_VehicleFamily": (
        "MATCH (p:ProductDocument {identifier: $a_id})"
        "<-[:DESCRIBED_IN]-(v:VehicleFamily) "
        "RETURN p AS ProductDocument, v AS VehicleFamily"
    ),
    "ProductDocument_to_VehicleVariant": (
        "MATCH (p:ProductDocument {identifier: $a_id})"
        "<-[:DESCRIBED_IN]-(:VehicleFamily)"
        "-[:HAS_VARIANT]->(v:VehicleVariant) "
        "RETURN p AS ProductDocument, v AS VehicleVariant"
    ),

    # ── ProductionOrder_to_ ───────────────────────────────────────────────────
    "ProductionOrder_to_ProductionPlan": (
        "MATCH (po:ProductionOrder {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(pov:ProductionOrderVersion)"
        "-[:INSTANTIATES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:CURRENT_VERSION]-(pp:ProductionPlan) "
        "RETURN po AS ProductionOrder, pp AS ProductionPlan"
    ),
    "ProductionOrder_to_ProductionProcess": (
        "MATCH (po:ProductionOrder {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(pov:ProductionOrderVersion)"
        "-[:INSTANTIATES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:REALIZES_PLAN]-(pp:ProductionProcess) "
        "RETURN po AS ProductionOrder, pp AS ProductionProcess"
    ),
    "ProductionOrder_to_VehicleVariant": (
        "MATCH (po:ProductionOrder {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(pov:ProductionOrderVersion)"
        "-[:ORDERS_VARIANT]->(vvs:VehicleVariantSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(v:VehicleVariant) "
        "RETURN po AS ProductionOrder, v AS VehicleVariant"
    ),
    "ProductionOrder_to_VehicleFamily": (
        "MATCH (po:ProductionOrder {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(pov:ProductionOrderVersion)"
        "-[:ORDERS_VARIANT]->(vvs:VehicleVariantSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(:VehicleVariant)"
        "<-[:HAS_VARIANT]-(v:VehicleFamily) "
        "RETURN po AS ProductionOrder, v AS VehicleFamily"
    ),
    "ProductionOrder_to_PartInstance": (
        "MATCH (po:ProductionOrder {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(pov:ProductionOrderVersion)"
        "-[:INSTANTIATES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:REALIZES_PLAN]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:CONSUMES_PART]->(pi:PartInstance) "
        "RETURN po AS ProductionOrder, pi AS PartInstance"
    ),
    "ProductionOrder_to_ToolInstance": (
        "MATCH (po:ProductionOrder {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(pov:ProductionOrderVersion)"
        "-[:INSTANTIATES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:REALIZES_PLAN]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:USE_TOOL]->(t:ToolInstance) "
        "RETURN po AS ProductionOrder, t AS ToolInstance"
    ),
    "ProductionOrder_to_EquipmentInstance": (
        "MATCH (po:ProductionOrder {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(pov:ProductionOrderVersion)"
        "-[:INSTANTIATES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:REALIZES_PLAN]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:USE_EQUIPMENT]->(e:EquipmentInstance) "
        "RETURN po AS ProductionOrder, e AS EquipmentInstance"
    ),
    "ProductionOrder_to_Personnel": (
        "MATCH (po:ProductionOrder {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(pov:ProductionOrderVersion)"
        "-[:INSTANTIATES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:REALIZES_PLAN]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:HAS_PARTICIPANT]->(p:Personnel) "
        "RETURN po AS ProductionOrder, p AS Personnel"
    ),
    "ProductionOrder_to_Supplier": (
        "MATCH (po:ProductionOrder {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(pov:ProductionOrderVersion)"
        "-[:INSTANTIATES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:REALIZES_PLAN]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:CONSUMES_PART]->(:PartInstance)"
        "-[:SUPPLIED_BY]->(s:Supplier) "
        "RETURN po AS ProductionOrder, s AS Supplier"
    ),
    "ProductionOrder_to_Operation": (
        "MATCH (po:ProductionOrder {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(pov:ProductionOrderVersion)"
        "-[:INSTANTIATES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:REALIZES_PLAN]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:INSTANTIATES_OPERATION]->(ov:OperationVersion)"
        "<-[:CURRENT_VERSION]-(op:Operation) "
        "RETURN po AS ProductionOrder, op AS Operation"
    ),
    "ProductionOrder_to_ManufacturingPlant": (
        "MATCH (po:ProductionOrder {identifier: $a_id})"
        "-[:ASSIGNED_TO]->(mp:ManufacturingPlant) "
        "RETURN po AS ProductionOrder, mp AS ManufacturingPlant"
    ),
    "ProductionOrder_to_AssemblyShop": (
        "MATCH (po:ProductionOrder {identifier: $a_id})"
        "-[:ASSIGNED_TO]->(:ManufacturingPlant)"
        "-[:HAS_SHOP]->(a:AssemblyShop) "
        "RETURN po AS ProductionOrder, a AS AssemblyShop"
    ),
    "ProductionOrder_to_Vehicle": (
        "MATCH (po:ProductionOrder {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(pov:ProductionOrderVersion)"
        "-[:INSTANTIATES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:REALIZES_PLAN]-(pp:ProductionProcess)"
        "-[:PRODUCES_VEHICLE]->(v:Vehicle) "
        "RETURN po AS ProductionOrder, v AS Vehicle"
    ),

    # ── ProductionPlan_to_ ────────────────────────────────────────────────────
    "ProductionPlan_to_ProductionProcess": (
        "MATCH (p:ProductionPlan {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(ppv:ProductionPlanVersion)"
        "<-[:REALIZES_PLAN]-(pp:ProductionProcess) "
        "RETURN p AS ProductionPlan, pp AS ProductionProcess"
    ),
    "ProductionPlan_to_VehicleVariant": (
        "MATCH (p:ProductionPlan {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(ppv:ProductionPlanVersion)"
        "-[:PLANS_VARIANT]->(vvs:VehicleVariantSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(v:VehicleVariant) "
        "RETURN p AS ProductionPlan, v AS VehicleVariant"
    ),
    "ProductionPlan_to_VehicleFamily": (
        "MATCH (p:ProductionPlan {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(ppv:ProductionPlanVersion)"
        "-[:PLANS_VARIANT]->(vvs:VehicleVariantSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(:VehicleVariant)"
        "<-[:HAS_VARIANT]-(v:VehicleFamily) "
        "RETURN p AS ProductionPlan, v AS VehicleFamily"
    ),
    "ProductionPlan_to_PartInstance": (
        "MATCH (p:ProductionPlan {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(ppv:ProductionPlanVersion)"
        "<-[:REALIZES_PLAN]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:CONSUMES_PART]->(pi:PartInstance) "
        "RETURN p AS ProductionPlan, pi AS PartInstance"
    ),
    "ProductionPlan_to_ToolInstance": (
        "MATCH (p:ProductionPlan {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(ppv:ProductionPlanVersion)"
        "<-[:REALIZES_PLAN]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:USE_TOOL]->(t:ToolInstance) "
        "RETURN p AS ProductionPlan, t AS ToolInstance"
    ),
    "ProductionPlan_to_EquipmentInstance": (
        "MATCH (p:ProductionPlan {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(ppv:ProductionPlanVersion)"
        "<-[:REALIZES_PLAN]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:USE_EQUIPMENT]->(e:EquipmentInstance) "
        "RETURN p AS ProductionPlan, e AS EquipmentInstance"
    ),
    "ProductionPlan_to_Personnel": (
        "MATCH (pp:ProductionPlan {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(ppv:ProductionPlanVersion)"
        "<-[:REALIZES_PLAN]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:HAS_PARTICIPANT]->(p:Personnel) "
        "RETURN pp AS ProductionPlan, p AS Personnel"
    ),
    "ProductionPlan_to_Supplier": (
        "MATCH (p:ProductionPlan {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(ppv:ProductionPlanVersion)"
        "<-[:REALIZES_PLAN]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:CONSUMES_PART]->(:PartInstance)"
        "-[:SUPPLIED_BY]->(s:Supplier) "
        "RETURN p AS ProductionPlan, s AS Supplier"
    ),
    "ProductionPlan_to_ProductionOrder": (
        "MATCH (pp:ProductionPlan {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(ppv:ProductionPlanVersion)"
        "<-[:INSTANTIATES_PLAN]-(pov:ProductionOrderVersion)"
        "<-[:CURRENT_VERSION]-(po:ProductionOrder) "
        "RETURN pp AS ProductionPlan, po AS ProductionOrder"
    ),
    "ProductionPlan_to_Operation": (
        "MATCH (pp:ProductionPlan {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(ppv:ProductionPlanVersion)"
        "<-[:REALIZES_PLAN]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:INSTANTIATES_OPERATION]->(ov:OperationVersion)"
        "<-[:CURRENT_VERSION]-(o:Operation) "
        "RETURN pp AS ProductionPlan, o AS Operation"
    ),
    "ProductionPlan_to_Vehicle": (
        "MATCH (pp:ProductionPlan {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(ppv:ProductionPlanVersion)"
        "<-[:REALIZES_PLAN]-(pp:ProductionProcess)"
        "-[:PRODUCES_VEHICLE]->(v:Vehicle) "
        "RETURN pp AS ProductionPlan, v AS Vehicle"
    ),
    "ProductionPlan_to_ManufacturingPlant": (
        "MATCH (pp:ProductionPlan {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(ppv:ProductionPlanVersion)"
        "<-[:INSTANTIATES_PLAN]-(pov:ProductionOrderVersion)"
        "<-[:CURRENT_VERSION]-(:ProductionOrder)"
        "-[:ASSIGNED_TO]->(o:ManufacturingPlant) "
        "RETURN pp AS ProductionPlan, o AS ManufacturingPlant"
    ),

    # ── ProductionProcess_to_ ─────────────────────────────────────────────────
    "ProductionProcess_to_Vehicle": (
        "MATCH (pp:ProductionProcess {identifier: $a_id})"
        "-[:PRODUCES_VEHICLE]->(v:Vehicle) "
        "RETURN pp AS ProductionProcess, v AS Vehicle"
    ),
    "ProductionProcess_to_VehicleVariant": (
        "MATCH (pp:ProductionProcess {identifier: $a_id})"
        "-[:REALIZES_PLAN]->(ppv:ProductionPlanVersion)"
        "-[:PLANS_VARIANT]->(vvs:VehicleVariantSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(v:VehicleVariant) "
        "RETURN pp AS ProductionProcess, v AS VehicleVariant"
    ),
    "ProductionProcess_to_VehicleFamily": (
        "MATCH (pp:ProductionProcess {identifier: $a_id})"
        "-[:REALIZES_PLAN]->(ppv:ProductionPlanVersion)"
        "-[:PLANS_VARIANT]->(vvs:VehicleVariantSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(:VehicleVariant)"
        "<-[:HAS_VARIANT]-(v:VehicleFamily) "
        "RETURN pp AS ProductionProcess, v AS VehicleFamily"
    ),
    "ProductionProcess_to_PartInstance": (
        "MATCH (pp:ProductionProcess {identifier: $a_id})"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:CONSUMES_PART]->(pi:PartInstance) "
        "RETURN pp AS ProductionProcess, pi AS PartInstance"
    ),
    "ProductionProcess_to_PartBatch": (
        "MATCH (pp:ProductionProcess {identifier: $a_id})"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:CONSUMES_PART]->(pi:PartBatch) "
        "RETURN pp AS ProductionProcess, pi AS PartBatch"
    ),
    "ProductionProcess_to_ToolInstance": (
        "MATCH (pp:ProductionProcess {identifier: $a_id})"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:USE_TOOL]->(t:ToolInstance) "
        "RETURN pp AS ProductionProcess, t AS ToolInstance"
    ),
    "ProductionProcess_to_EquipmentInstance": (
        "MATCH (pp:ProductionProcess {identifier: $a_id})"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:USE_EQUIPMENT]->(e:EquipmentInstance) "
        "RETURN pp AS ProductionProcess, e AS EquipmentInstance"
    ),
    "ProductionProcess_to_Personnel": (
        "MATCH (pp:ProductionProcess {identifier: $a_id})"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:HAS_PARTICIPANT]->(p:Personnel) "
        "RETURN pp AS ProductionProcess, p AS Personnel"
    ),
    "Personnel_to_ProductionProcess": (
        "MATCH (p:Personnel {identifier: $a_id})"
        "<-[:HAS_PARTICIPANT]-(task:OperationalTask)"
        "<-[:HAS_TASK]-(pp:ProductionProcess) "
        "RETURN p AS Personnel, pp AS ProductionProcess"
    ),
    "ProductionProcess_to_Supplier": (
        "MATCH (pp:ProductionProcess {identifier: $a_id})"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:CONSUMES_PART]->(:PartInstance)"
        "-[:SUPPLIED_BY]->(s:Supplier) "
        "RETURN pp AS ProductionProcess, s AS Supplier"
    ),
    "ProductionProcess_to_ProductionOrder": (
        "MATCH (pp:ProductionProcess {identifier: $a_id})"
        "-[:REALIZES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:INSTANTIATES_PLAN]-(pov:ProductionOrderVersion)"
        "<-[:CURRENT_VERSION]-(po:ProductionOrder) "
        "RETURN pp AS ProductionProcess, po AS ProductionOrder"
    ),
    "ProductionProcess_to_ProductionPlan": (
        "MATCH (pp:ProductionProcess {identifier: $a_id})"
        "-[:REALIZES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:CURRENT_VERSION]-(pl:ProductionPlan) "
        "RETURN pp AS ProductionProcess, pl AS ProductionPlan"
    ),
    "ProductionProcess_to_AssemblyShop": (
        "MATCH (pp:ProductionProcess {identifier: $a_id})"
        "-[:OCCURS_AT]->(a:AssemblyShop) "
        "RETURN pp AS ProductionProcess, a AS AssemblyShop"
    ),
    "ProductionProcess_to_ManufacturingPlant": (
        "MATCH (pp:ProductionProcess {identifier: $a_id})"
        "-[:REALIZES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:INSTANTIATES_PLAN]-(pov:ProductionOrderVersion)"
        "<-[:CURRENT_VERSION]-(:ProductionOrder)"
        "-[:ASSIGNED_TO]->(mp:ManufacturingPlant) "
        "RETURN pp AS ProductionProcess, mp AS ManufacturingPlant"
    ),
    "ProductionProcess_to_Operation": (
        "MATCH (pp:ProductionProcess {identifier: $a_id})"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:INSTANTIATES_OPERATION]->(ov:OperationVersion)"
        "<-[:CURRENT_VERSION]-(op:Operation) "
        "RETURN pp AS ProductionProcess, op AS Operation"
    ),
    "ProductionProcess_to_OperationalTask": (
        "MATCH (pp:ProductionProcess {identifier: $a_id})"
        "-[:HAS_TASK]->(o:OperationalTask) "
        "RETURN pp AS ProductionProcess, o AS OperationalTask"
    ),

    # ── OperationalTask_to_ ───────────────────────────────────────────────────
    "OperationalTask_to_PartInstance": (
        "MATCH (o:OperationalTask {identifier: $a_id})"
        "-[:CONSUMES_PART]->(pi:PartInstance) "
        "RETURN o AS OperationalTask, pi AS PartInstance"
    ),
    "OperationalTask_to_ToolInstance": (
        "MATCH (o:OperationalTask {identifier: $a_id})"
        "-[:USE_TOOL]->(t:ToolInstance) "
        "RETURN o AS OperationalTask, t AS ToolInstance"
    ),
    "OperationalTask_to_EquipmentInstance": (
        "MATCH (o:OperationalTask {identifier: $a_id})"
        "-[:USE_EQUIPMENT]->(e:EquipmentInstance) "
        "RETURN o AS OperationalTask, e AS EquipmentInstance"
    ),
    "OperationalTask_to_Personnel": (
        "MATCH (o:OperationalTask {identifier: $a_id})"
        "-[:HAS_PARTICIPANT]->(p:Personnel) "
        "RETURN o AS OperationalTask, p AS Personnel"
    ),
    "OperationalTask_to_Supplier": (
        "MATCH (o:OperationalTask {identifier: $a_id})"
        "-[:CONSUMES_PART]->(:PartInstance)"
        "-[:SUPPLIED_BY]->(s:Supplier) "
        "RETURN o AS OperationalTask, s AS Supplier"
    ),
    "OperationalTask_to_AssemblyShop": (
        "MATCH (ot:OperationalTask {identifier: $a_id})"
        "<-[:HAS_TASK]-(pp:ProductionProcess)"
        "-[:OCCURS_AT]->(a:AssemblyShop) "
        "RETURN ot AS OperationalTask, a AS AssemblyShop"
    ),
    "OperationalTask_to_ManufacturingPlant": (
        "MATCH (ot:OperationalTask {identifier: $a_id})"
        "<-[:HAS_TASK]-(pp:ProductionProcess)"
        "-[:REALIZES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:INSTANTIATES_PLAN]-(pov:ProductionOrderVersion)"
        "<-[:CURRENT_VERSION]-(:ProductionOrder)"
        "-[:ASSIGNED_TO]->(mp:ManufacturingPlant) "
        "RETURN ot AS OperationalTask, mp AS ManufacturingPlant"
    ),
    "OperationalTask_to_Operation": (
        "MATCH (ot:OperationalTask {identifier: $a_id})"
        "-[:INSTANTIATES_OPERATION]->(ov:OperationVersion)"
        "<-[:CURRENT_VERSION]-(op:Operation) "
        "RETURN ot AS OperationalTask, op AS Operation"
    ),
    "OperationalTask_to_ProductionProcess": (
        "MATCH (ot:OperationalTask {identifier: $a_id})"
        "<-[:HAS_TASK]-(pp:ProductionProcess) "
        "RETURN ot AS OperationalTask, pp AS ProductionProcess"
    ),

    # ── Part_to_ ──────────────────────────────────────────────────────────────
    "Part_to_PartInstance": (
        "MATCH (p:Part {identifier: $a_id})"
        "-[:CURRENT_SPECIFICATION]->(ps:PartSpecification)"
        "<-[:CONFIGURED_TO]-(pi:PartInstance) "
        "RETURN p AS Part, pi AS PartInstance"
    ),
    "Part_to_PartBatch": (
        "MATCH (p:Part {identifier: $a_id})"
        "-[:CURRENT_SPECIFICATION]->(ps:PartSpecification)"
        "<-[:CONFIGURED_TO]-(pi:PartBatch) "
        "RETURN p AS Part, pi AS PartBatch"
    ),
    "Part_to_Supplier": (
        "MATCH (p:Part {identifier: $a_id})"
        "-[:CURRENT_SPECIFICATION]->(ps:PartSpecification)"
        "-[:HAS_SUPPLIER]->(s:Supplier) "
        "RETURN p AS Part, s AS Supplier"
    ),
    "Part_to_VehicleVariant": (
        "MATCH (p:Part {identifier: $a_id})"
        "-[:CURRENT_SPECIFICATION]->(ps:PartSpecification)"
        "<-[:HAS_BOMITEM]-(vvs:VehicleVariantSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(v:VehicleVariant) "
        "RETURN p AS Part, v AS VehicleVariant"
    ),
    "VehicleVariant_to_Part": (
        "MATCH (p:Part)"
        "-[:CURRENT_SPECIFICATION]->(ps:PartSpecification)"
        "<-[:HAS_BOMITEM]-(vvs:VehicleVariantSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(v:VehicleVariant {identifier: $a_id}) "
        "RETURN p AS Part, v AS VehicleVariant"
    ),
    "Part_to_VehicleFamily": (
        "MATCH (p:Part {identifier: $a_id})"
        "-[:CURRENT_SPECIFICATION]->(ps:PartSpecification)"
        "<-[:HAS_BOMITEM]-(vvs:VehicleVariantSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(:VehicleVariant)"
        "<-[:HAS_VARIANT]-(v:VehicleFamily) "
        "RETURN p AS Part, v AS VehicleFamily"
    ),

    # ── PartInstance_to_ ──────────────────────────────────────────────────────
    "PartInstance_to_Vehicle": (
        "MATCH (pi:PartInstance {identifier: $a_id})"
        "<-[:CONSUMES_PART]-(task:OperationalTask)"
        "<-[:HAS_TASK]-(pp:ProductionProcess)"
        "-[:PRODUCES_VEHICLE]->(v:Vehicle) "
        "RETURN pi AS PartInstance, v AS Vehicle"
    ),
    "PartBatch_to_Vehicle": (
        "MATCH (pi:PartBatch {batchNumber: $a_id})"
        "<-[:CONSUMES_PART]-(task:OperationalTask)"
        "<-[:HAS_TASK]-(pp:ProductionProcess)"
        "-[:PRODUCES_VEHICLE]->(v:Vehicle) "
        "RETURN pi AS PartBatch, v AS Vehicle"
    ),
    "PartInstance_to_ProductionOrder": (
        "MATCH (pi:PartInstance {identifier: $a_id})"
        "<-[:CONSUMES_PART]-(task:OperationalTask)"
        "<-[:HAS_TASK]-(pp:ProductionProcess)"
        "-[:REALIZES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:INSTANTIATES_PLAN]-(pov:ProductionOrderVersion)"
        "<-[:CURRENT_VERSION]-(po:ProductionOrder) "
        "RETURN pi AS PartInstance, po AS ProductionOrder"
    ),
    "PartBatch_to_ProductionOrder": (
        "MATCH (pi:PartBatch {batchNumber: $a_id})"
        "<-[:CONSUMES_PART]-(task:OperationalTask)"
        "<-[:HAS_TASK]-(pp:ProductionProcess)"
        "-[:REALIZES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:INSTANTIATES_PLAN]-(pov:ProductionOrderVersion)"
        "<-[:CURRENT_VERSION]-(po:ProductionOrder) "
        "RETURN pi AS PartBatch, po AS ProductionOrder"
    ),
        "PartBatch_to_Operation": (
        "MATCH (pi:PartBatch {batchNumber: $a_id})"
        "<-[:CONSUMES_PART]-(task:OperationalTask)"
        "-[:INSTANTIATES_OPERATION]->(ov:OperationVersion)"
        "<-[:CURRENT_VERSION]-(op:Operation)"
        "RETURN pi AS PartBatch, op AS Operation"
    ),
    "PartInstance_to_ProductionPlan": (
        "MATCH (pi:PartInstance {identifier: $a_id})"
        "<-[:CONSUMES_PART]-(task:OperationalTask)"
        "<-[:HAS_TASK]-(pp:ProductionProcess)"
        "-[:REALIZES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:CURRENT_VERSION]-(pp:ProductionPlan) "
        "RETURN pi AS PartInstance, pp AS ProductionPlan"
    ),
    "PartInstance_to_AssemblyShop": (
        "MATCH (pi:PartInstance {identifier: $a_id})"
        "<-[:CONSUMES_PART]-(task:OperationalTask)"
        "<-[:HAS_TASK]-(proc:ProductionProcess)"
        "-[:OCCURS_AT]->(a:AssemblyShop) "
        "RETURN pi AS PartInstance, a AS AssemblyShop"
    ),
    "PartInstance_to_ManufacturingPlant": (
        "MATCH (pi:PartInstance {identifier: $a_id})"
        "<-[:CONSUMES_PART]-(task:OperationalTask)"
        "<-[:HAS_TASK]-(pp:ProductionProcess)"
        "-[:REALIZES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:INSTANTIATES_PLAN]-(pov:ProductionOrderVersion)"
        "<-[:CURRENT_VERSION]-(:ProductionOrder)"
        "-[:ASSIGNED_TO]->(mp:ManufacturingPlant) "
        "RETURN pi AS PartInstance, mp AS ManufacturingPlant"
    ),

    "BatchPart_to_ManufacturingPlant": (
        "MATCH (pi:BatchPart {bacthNumber: $a_id})"
        "<-[:CONSUMES_PART]-(task:OperationalTask)"
        "<-[:HAS_TASK]-(pp:ProductionProcess)"
        "-[:REALIZES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:INSTANTIATES_PLAN]-(pov:ProductionOrderVersion)"
        "<-[:CURRENT_VERSION]-(:ProductionOrder)"
        "-[:ASSIGNED_TO]->(mp:ManufacturingPlant) "
        "RETURN pi AS BatchPart, mp AS ManufacturingPlant"
    ),

    "PartInstance_to_Supplier": (
        "MATCH (pi:PartInstance {identifier: $a_id})"
        "-[:SUPPLIED_BY]->(s:Supplier) "
        "RETURN pi AS PartInstance, s AS Supplier"
    ),

    # ── Tool_to_ ──────────────────────────────────────────────────────────────
    "Tool_to_ToolInstance": (
        "MATCH (t:Tool {identifier: $a_id})"
        "-[:CURRENT_SPECIFICATION]->(ts:ToolSpecification)"
        "<-[:CONFIGURED_TO]-(ti:ToolInstance) "
        "RETURN t AS Tool, ti AS ToolInstance"
    ),
    "Tool_to_VehicleVariant": (
        "MATCH (t:Tool {identifier: $a_id})"
        "-[:CURRENT_SPECIFICATION]->(ts:ToolSpecification)"
        "<-[:REQUIRES_TOOL]-(ov:OperationVersion)"
        "-[:APPLICABLE_TO]->(vvs:VehicleVariantSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(v:VehicleVariant) "
        "RETURN t AS Tool, v AS VehicleVariant"
    ),
    "Tool_to_VehicleFamily": (
        "MATCH (t:Tool {identifier: $a_id})"
        "-[:CURRENT_SPECIFICATION]->(ts:ToolSpecification)"
        "<-[:REQUIRES_TOOL]-(ov:OperationVersion)"
        "-[:APPLICABLE_TO]->(vvs:VehicleVariantSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(:VehicleVariant)"
        "<-[:HAS_VARIANT]-(v:VehicleFamily) "
        "RETURN t AS Tool, v AS VehicleFamily"
    ),

    # ── ToolInstance_to_ ──────────────────────────────────────────────────────
    "ToolInstance_to_Vehicle": (
        "MATCH (pi:ToolInstance {identifier: $a_id})"
        "<-[:USE_TOOL]-(task:OperationalTask)"
        "<-[:HAS_TASK]-(pp:ProductionProcess)"
        "-[:PRODUCES_VEHICLE]->(v:Vehicle) "
        "RETURN pi AS ToolInstance, v AS Vehicle"
    ),
    "ToolInstance_to_ProductionOrder": (
        "MATCH (pi:ToolInstance {identifier: $a_id})"
        "<-[:USE_TOOL]-(task:OperationalTask)"
        "<-[:HAS_TASK]-(pp:ProductionProcess)"
        "-[:REALIZES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:INSTANTIATES_PLAN]-(pov:ProductionOrderVersion)"
        "<-[:CURRENT_VERSION]-(po:ProductionOrder) "
        "RETURN pi AS ToolInstance, po AS ProductionOrder"
    ),
    "ToolInstance_to_ProductionPlan": (
        "MATCH (pi:ToolInstance {identifier: $a_id})"
        "<-[:USE_TOOL]-(task:OperationalTask)"
        "<-[:HAS_TASK]-(pp:ProductionProcess)"
        "-[:REALIZES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:CURRENT_VERSION]-(pp:ProductionPlan) "
        "RETURN pi AS ToolInstance, pp AS ProductionPlan"
    ),
    "ToolInstance_to_AssemblyShop": (
        "MATCH (pi:ToolInstance {identifier: $a_id})"
        "<-[:USE_TOOL]-(task:OperationalTask)"
        "<-[:HAS_TASK]-(proc:ProductionProcess)"
        "-[:OCCURS_AT]->(a:AssemblyShop) "
        "RETURN pi AS ToolInstance, a AS AssemblyShop"
    ),
    "ToolInstance_to_ManufacturingPlant": (
        "MATCH (pi:ToolInstance {identifier: $a_id})"
        "<-[:USE_TOOL]-(task:OperationalTask)"
        "<-[:HAS_TASK]-(pp:ProductionProcess)"
        "-[:REALIZES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:INSTANTIATES_PLAN]-(pov:ProductionOrderVersion)"
        "<-[:CURRENT_VERSION]-(:ProductionOrder)"
        "-[:ASSIGNED_TO]->(mp:ManufacturingPlant) "
        "RETURN pi AS ToolInstance, mp AS ManufacturingPlant"
    ),

    # ── Equipment_to_ ─────────────────────────────────────────────────────────
    "Equipment_to_EquipmentInstance": (
        "MATCH (e:Equipment {identifier: $a_id})"
        "-[:CURRENT_SPECIFICATION]->(es:EquipmentSpecification)"
        "<-[:CONFIGURED_TO]-(ei:EquipmentInstance) "
        "RETURN e AS Equipment, ei AS EquipmentInstance"
    ),
    "Equipment_to_VehicleVariant": (
        "MATCH (e:Equipment {identifier: $a_id})"
        "-[:CURRENT_SPECIFICATION]->(es:EquipmentSpecification)"
        "<-[:REQUIRES_EQUIPMENT]-(ov:OperationVersion)"
        "-[:APPLICABLE_TO]->(vvs:VehicleVariantSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(v:VehicleVariant) "
        "RETURN e AS Equipment, v AS VehicleVariant"
    ),
    "Equipment_to_VehicleFamily": (
        "MATCH (e:Equipment {identifier: $a_id})"
        "-[:CURRENT_SPECIFICATION]->(es:EquipmentSpecification)"
        "<-[:REQUIRES_EQUIPMENT]-(ov:OperationVersion)"
        "-[:APPLICABLE_TO]->(vvs:VehicleVariantSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(:VehicleVariant)"
        "<-[:HAS_VARIANT]-(v:VehicleFamily) "
        "RETURN e AS Equipment, v AS VehicleFamily"
    ),

        
    "ManualTool_to_Operation": (
        "MATCH (o:Operation)"
        "-[:CURRENT_VERSION]->(ov:OperationVersion)"
        "-[:REQUIRES_TOOL]->(mts:ManualToolSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(m:ManualTool {identifier: $a_id}) "
        "RETURN o AS Operation, m AS ManualTool"
    ),
    "PrecisionTool_to_Operation": (
        "MATCH (o:Operation)"
        "-[:CURRENT_VERSION]->(ov:OperationVersion)"
        "-[:REQUIRES_TOOL]->(pts:PrecisionToolSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(p:PrecisionTool {identifier: $a_id}) "
        "RETURN o AS Operation, p AS PrecisionTool"
    ),
    "RoboticEquipment_to_Operation": (
        "MATCH (o:Operation)"
        "-[:CURRENT_VERSION]->(ov:OperationVersion)"
        "-[:REQUIRES_EQUIPMENT]->(res:RoboticEquipmentSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(p:RoboticEquipment {identifier: $a_id}) "
        "RETURN o AS Operation, p AS RoboticEquipment"
    ),
    "ProcessEquipment_to_Operation": (
        "MATCH (o:Operation)"
        "-[:CURRENT_VERSION]->(ov:OperationVersion)"
        "-[:REQUIRES_EQUIPMENT]->(pes:ProcessEquipmentSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(p:ProcessEquipment {identifier: $a_id}) "
        "RETURN o AS Operation, p AS ProcessEquipment"
    ),
    "DiagnosticEquipment_to_Operation": (
        "MATCH (o:Operation)"
        "-[:CURRENT_VERSION]->(ov:OperationVersion)"
        "-[:REQUIRES_EQUIPMENT]->(des:DiagnosticEquipmentSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(p:DiagnosticEquipment {identifier: $a_id}) "
        "RETURN o AS Operation, p AS DiagnosticEquipment"
    ),
    "MaterialHandlingEquipment_to_Operation": (
        "MATCH (o:Operation)"
        "-[:CURRENT_VERSION]->(ov:OperationVersion)"
        "-[:REQUIRES_EQUIPMENT]->(mhes:MaterialHandlingEquipmentSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(p:MaterialHandlingEquipment {identifier: $a_id}) "
        "RETURN o AS Operation, p AS MaterialHandlingEquipment"
    ),

    # ── EquipmentInstance_to_ ─────────────────────────────────────────────────
    "EquipmentInstance_to_Vehicle": (
        "MATCH (pi:EquipmentInstance {identifier: $a_id})"
        "<-[:USE_EQUIPMENT]-(task:OperationalTask)"
        "<-[:HAS_TASK]-(pp:ProductionProcess)"
        "-[:PRODUCES_VEHICLE]->(v:Vehicle) "
        "RETURN pi AS EquipmentInstance, v AS Vehicle"
    ),
    "EquipmentInstance_to_ProductionOrder": (
        "MATCH (pi:EquipmentInstance {identifier: $a_id})"
        "<-[:USE_EQUIPMENT]-(task:OperationalTask)"
        "<-[:HAS_TASK]-(pp:ProductionProcess)"
        "-[:REALIZES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:INSTANTIATES_PLAN]-(pov:ProductionOrderVersion)"
        "<-[:CURRENT_VERSION]-(po:ProductionOrder) "
        "RETURN pi AS EquipmentInstance, po AS ProductionOrder"
    ),
    "EquipmentInstance_to_ProductionPlan": (
        "MATCH (pi:EquipmentInstance {identifier: $a_id})"
        "<-[:USE_EQUIPMENT]-(task:OperationalTask)"
        "<-[:HAS_TASK]-(pp:ProductionProcess)"
        "-[:REALIZES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:CURRENT_VERSION]-(pp:ProductionPlan) "
        "RETURN pi AS EquipmentInstance, pp AS ProductionPlan"
    ),
    "EquipmentInstance_to_AssemblyShop": (
        "MATCH (pi:EquipmentInstance {identifier: $a_id})"
        "<-[:USE_EQUIPMENT]-(task:OperationalTask)"
        "<-[:HAS_TASK]-(proc:ProductionProcess)"
        "-[:OCCURS_AT]->(a:AssemblyShop) "
        "RETURN pi AS EquipmentInstance, a AS AssemblyShop"
    ),
    "EquipmentInstance_to_ManufacturingPlant": (
        "MATCH (pi:EquipmentInstance {identifier: $a_id})"
        "<-[:USE_EQUIPMENT]-(task:OperationalTask)"
        "<-[:HAS_TASK]-(pp:ProductionProcess)"
        "-[:REALIZES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:INSTANTIATES_PLAN]-(pov:ProductionOrderVersion)"
        "<-[:CURRENT_VERSION]-(:ProductionOrder)"
        "-[:ASSIGNED_TO]->(mp:ManufacturingPlant) "
        "RETURN pi AS EquipmentInstance, mp AS ManufacturingPlant"
    ),

    # ── Personnel_to_ ─────────────────────────────────────────────────────────
    "Personnel_to_OperationalTask": (
        "MATCH (p:Personnel {identifier: $a_id})"
        "<-[:HAS_PARTICIPANT]-(o:OperationalTask) "
        "RETURN p AS Personnel, o AS OperationalTask"
    ),
    "Personnel_to_Operation": (
        "MATCH (p:Personnel {identifier: $a_id})"
        "<-[:HAS_PARTICIPANT]-(task:OperationalTask)"
        "-[:INSTANTIATES_OPERATION]->(ov:OperationVersion)"
        "<-[:CURRENT_VERSION]-(o:Operation) "
        "RETURN p AS Personnel, o AS Operation"
    ),
    # "Personnel_to_WorkStep": (
    #     "MATCH (p:Personnel {identifier: $a_id})"
    #     "<-[:HAS_PARTICIPANT]-(task:OperationalTask)"
    #     "-[:INSTANTIATES_OPERATION]->(ov:OperationVersion)"
    #     "-[:HAS_STEP]-(wsv:WorkStepVersion)"
    #     "<-[:CURRENT_VERSION]-(w:WorkStep) "
    #     "RETURN p AS Personnel, w AS WorkStep"
    # ),
    "Personnel_to_Part": (
        "MATCH (pl:Personnel {identifier: $a_id})"
        "<-[:HAS_PARTICIPANT]-(task:OperationalTask)"
        "-[:INSTANTIATES_OPERATION]->(ov:OperationVersion)"
        "-[:REQUIRES_PART]->(ps:PartSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(p:Part) "
        "RETURN pl AS Personnel, p AS Part"
    ),
    "Personnel_to_Tool": (
        "MATCH (pl:Personnel {identifier: $a_id})"
        "<-[:HAS_PARTICIPANT]-(task:OperationalTask)"
        "-[:INSTANTIATES_OPERATION]->(ov:OperationVersion)"
        "-[:REQUIRES_TOOL]->(ts:ToolSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(t:Tool) "
        "RETURN pl AS Personnel, t AS Tool"
    ),
    "Personnel_to_Equipment": (
        "MATCH (p:Personnel {identifier: $a_id})"
        "<-[:HAS_PARTICIPANT]-(task:OperationalTask)"
        "-[:INSTANTIATES_OPERATION]->(ov:OperationVersion)"
        "-[:REQUIRES_EQUIPMENT]->(es:EquipmentSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(e:Equipment) "
        "RETURN p AS Personnel, e AS Equipment"
    ),
    "Supplier_to_Part": (
        "MATCH (p:Part)"
        "-[:CURRENT_SPECIFICATION]->(ps:PartSpecification)"
        "-[:HAS_SUPPLIER]->(s:Supplier {identifier: $a_id}) "
        "RETURN s AS Supplier, p AS Part "
    ),
    "Supplier_to_PartInstance": (
        "MATCH (pi:PartInstance )"
        "-[:SUPPLIED_BY]->(s:Supplier {identifier: $a_id}) "
        "RETURN pi AS PartInstance, s AS Supplier"
    ),
    "Supplier_to_AssemblyShop": (
        "MATCH (a:AssemblyShop)"
        "<-[:OCCURS_AT]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:CONSUMES_PART]->(:PartInstance)"
        "-[:SUPPLIED_BY]->(s:Supplier {identifier: $a_id}) "
        "RETURN a AS AssemblyShop, s AS Supplier"
    ),
    "Supplier_to_ManufacturingPlant": (
        "MATCH (o:ManufacturingPlant)"
        "<-[:ASSIGNED_TO]-(:ProductionOrder)"
        "-[:CURRENT_VERSION]->(pov:ProductionOrderVersion)"
        "-[:INSTANTIATES_PLAN]->(ppv:ProductionPlanVersion)"
        "<-[:REALIZES_PLAN]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:CONSUMES_PART]->(:PartInstance)"
        "-[:SUPPLIED_BY]->(s:Supplier {identifier: $a_id}) "
        "RETURN o AS ManufacturingPlant, s AS Supplier"
    ),
    "Supplier_to_Vehicle": (
        "MATCH (v:Vehicle)"
        "<-[:PRODUCES_VEHICLE]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:CONSUMES_PART]->(:PartInstance)"
        "-[:SUPPLIED_BY]->(s:Supplier {identifier: $a_id}) "
        "RETURN v AS Vehicle, s AS Supplier"
    ),

    # ── WorkStep ──────────────────────────────────────────────────────────────
    # "WorkStep_to_Operation": (
    #     "MATCH (ws:WorkStep {identifier: $a_id})"
    #     "-[:CURRENT_VERSION]->(wsv:WorkStepVersion)"
    #     "<-[:HAS_STEP]-(ov:OperationVersion)"
    #     "<-[:CURRENT_VERSION]-(o:Operation) "
    #     "RETURN ws AS WorkStep, o AS Operation"
    # ),
    # "WorkStep_to_OperationalTask": (
    #     "MATCH (ws:WorkStep {identifier: $a_id})"
    #     "-[:CURRENT_VERSION]->(wsv:WorkStepVersion)"
    #     "<-[:HAS_STEP]-(ov:OperationVersion)"
    #     "<-[:INSTANTIATES_OPERATION]-(ot:OperationalTask) "
    #     "RETURN ws AS WorkStep, ot AS OperationalTask"
    # ),
    # "WorkStep_to_VehicleVariant": (
    #     "MATCH (ws:WorkStep {identifier: $a_id})"
    #     "-[:CURRENT_VERSION]->(wsv:WorkStepVersion)"
    #     "<-[:HAS_STEP]-(ov:OperationVersion)"
    #     "-[:APPLICABLE_TO]->(vvs:VehicleVariantSpecification)"
    #     "<-[:CURRENT_SPECIFICATION]-(vv:VehicleVariant) "
    #     "RETURN ws AS WorkStep, vv AS VehicleVariant"
    # ),
    # "WorkStep_to_VehicleFamily": (
    #     "MATCH (ws:WorkStep {identifier: $a_id})"
    #     "-[:CURRENT_VERSION]->(wsv:WorkStepVersion)"
    #     "<-[:HAS_STEP]-(ov:OperationVersion)"
    #     "-[:APPLICABLE_TO]->(vvs:VehicleVariantSpecification)"
    #     "<-[:CURRENT_SPECIFICATION]-(:VehicleVariant)"
    #     "<-[:HAS_VARIANT]-(vf:VehicleFamily) "
    #     "RETURN ws AS WorkStep, vf AS VehicleFamily"
    # ),

    # ── OperationalTask (missing reverses) ────────────────────────────────────
    # "OperationalTask_to_WorkStep": (
    #     "MATCH (ot:OperationalTask {identifier: $a_id})"
    #     "-[:INSTANTIATES_OPERATION]->(ov:OperationVersion)"
    #     "-[:HAS_STEP]->(wsv:WorkStepVersion)"
    #     "<-[:CURRENT_VERSION]-(ws:WorkStep) "
    #     "RETURN ot AS OperationalTask, ws AS WorkStep"
    # ),
    "OperationalTask_to_Vehicle": (
        "MATCH (ot:OperationalTask {identifier: $a_id})"
        "<-[:HAS_TASK]-(pp:ProductionProcess)"
        "-[:PRODUCES_VEHICLE]->(v:Vehicle) "
        "RETURN ot AS OperationalTask, v AS Vehicle"
    ),

    # ── ProductionShop (missing reverses) ─────────────────────────────────────
    "ProductionShop_to_ManufacturingPlant": (
        "MATCH (ps:ProductionShop {identifier: $a_id})"
        "<-[:HAS_SHOP]-(mp:ManufacturingPlant) "
        "RETURN ps AS ProductionShop, mp AS ManufacturingPlant"
    ),
    "ProductionShop_to_ProductionProcess": (
        "MATCH (ps:ProductionShop {identifier: $a_id})"
        "<-[:OCCURS_AT]-(pp:ProductionProcess) "
        "RETURN ps AS ProductionShop, pp AS ProductionProcess"
    ),
    "ProductionShop_to_Operation": (
        "MATCH (ps:ProductionShop {identifier: $a_id})"
        "<-[:QUALIFIED_FOR]-(o:Operation) "
        "RETURN ps AS ProductionShop, o AS Operation"
    ),
    # "ProductionShop_to_WorkStep": (
    #     "MATCH (ps:ProductionShop {identifier: $a_id})"
    #     "<-[:QUALIFIED_FOR]-(:Operation)"
    #     "-[:CURRENT_VERSION]->(ov:OperationVersion)"
    #     "-[:HAS_STEP]->(wsv:WorkStepVersion)"
    #     "<-[:CURRENT_VERSION]-(ws:WorkStep) "
    #     "RETURN ps AS ProductionShop, ws AS WorkStep"
    # ),
    "ProductionShop_to_Vehicle": (
        "MATCH (ps:ProductionShop {identifier: $a_id})"
        "<-[:OCCURS_AT]-(pp:ProductionProcess)"
        "-[:PRODUCES_VEHICLE]->(v:Vehicle) "
        "RETURN ps AS ProductionShop, v AS Vehicle"
    ),
    "ProductionShop_to_Personnel": (
        "MATCH (ps:ProductionShop {identifier: $a_id})"
        "<-[:OCCURS_AT]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:HAS_PARTICIPANT]->(p:Personnel) "
        "RETURN ps AS ProductionShop, p AS Personnel"
    ),
    "ProductionShop_to_Part": (
        "MATCH (ps:ProductionShop {identifier: $a_id})"
        "<-[:OCCURS_AT]-(pp:ProductionProcess)"
        "-[:HAS_TASK]->(task:OperationalTask)"
        "-[:CONSUMES_PART]->(:PartInstance)"
        "-[:INSTANCE_OF]->(p:Part) "
        "RETURN ps AS ProductionShop, p AS Part"
    ),

    # ── Personnel (missing instance paths) ───────────────────────────────────
    "Personnel_to_Vehicle": (
        "MATCH (p:Personnel {identifier: $a_id})"
        "<-[:HAS_PARTICIPANT]-(task:OperationalTask)"
        "<-[:HAS_TASK]-(pp:ProductionProcess)"
        "-[:PRODUCES_VEHICLE]->(v:Vehicle) "
        "RETURN p AS Personnel, v AS Vehicle"
    ),
    "Personnel_to_PartInstance": (
        "MATCH (p:Personnel {identifier: $a_id})"
        "<-[:HAS_PARTICIPANT]-(task:OperationalTask)"
        "-[:CONSUMES_PART]->(pi:PartInstance) "
        "RETURN p AS Personnel, pi AS PartInstance"
    ),
    "Personnel_to_ToolInstance": (
        "MATCH (p:Personnel {identifier: $a_id})"
        "<-[:HAS_PARTICIPANT]-(task:OperationalTask)"
        "-[:USE_TOOL]->(ti:ToolInstance) "
        "RETURN p AS Personnel, ti AS ToolInstance"
    ),
    "Personnel_to_EquipmentInstance": (
        "MATCH (p:Personnel {identifier: $a_id})"
        "<-[:HAS_PARTICIPANT]-(task:OperationalTask)"
        "-[:USE_EQUIPMENT]->(ei:EquipmentInstance) "
        "RETURN p AS Personnel, ei AS EquipmentInstance"
    ),

    # ── Part (reverse lookup paths) ───────────────────────────────────────────
    "Part_to_Vehicle": (
        "MATCH (p:Part {identifier: $a_id})"
        "-[:CURRENT_SPECIFICATION]->(ps:PartSpecification)"
        "<-[:HAS_BOMITEM]-(vvs:VehicleVariantSpecification)"
        "<-[:CURRENT_SPECIFICATION]-(:VehicleVariant)"
        "<-[:INSTANCE_OF]-(v:Vehicle) "
        "RETURN p AS Part, v AS Vehicle"
    ),
    "Part_to_Operation": (
        "MATCH (p:Part {identifier: $a_id})"
        "-[:CURRENT_SPECIFICATION]->(ps:PartSpecification)"
        "<-[:REQUIRES_PART]-(ov:OperationVersion)"
        "<-[:CURRENT_VERSION]-(o:Operation) "
        "RETURN p AS Part, o AS Operation"
    ),

    # ── ProductDocument (missing paths) ──────────────────────────────────────
    "ProductDocument_to_Operation": (
        "MATCH (pd:ProductDocument {identifier: $a_id})"
        "-[:CURRENT_VERSION]->(:ProductDocumentVersion)"
        "<-[:DERIVED_FROM]-(ov:OperationVersion)"
        "<-[:CURRENT_VERSION]-(o:Operation) "
        "RETURN pd AS ProductDocument, o AS Operation"
    ),
}

# ── Runtime-loaded custom primitives (from Neo4j via UI) ──────────────────────
_CUSTOM_PRIMITIVES: dict[str, str] = {}


def load_custom_primitives() -> None:
    """
    Load primitives with category='primitive' from Neo4j RetrievalTemplate nodes
    and merge them into the active lookup table. Call once at app startup or after
    a UI save.
    """
    try:
        from services.template_service import list_templates
        for tpl in list_templates():
            if tpl.get("category") == "primitive" and tpl.get("name") and tpl.get("cypher"):
                _CUSTOM_PRIMITIVES[tpl["name"]] = tpl["cypher"]
    except Exception:
        pass


def _build_params(label_a: str, id_a: str, label_b: str, id_b: str | None) -> dict:
    """Return Cypher params. All built-in primitives filter by $a_id on the source node."""
    return {"a_id": id_a}


def lookup_primitive(label_a: str, id_a: str, label_b: str, id_b: str | None = None) -> dict | None:
    """
    Build the key from the two entity labels and try both orderings.
    Checks built-in GRAPH_PRIMITIVES first, then runtime custom primitives.

    Key pattern: f"{label_a}_to_{label_b}"

    Returns {"cypher", "params", "key"} or None if no primitive exists for this pair.
    """
    combined = {**GRAPH_PRIMITIVES, **_CUSTOM_PRIMITIVES}

    for a, id_a_val, b, id_b_val in [
        (label_a, id_a, label_b, id_b),
        (label_b, id_b, label_a, id_a),
    ]:
        key = f"{a}_to_{b}"
        if key in combined:
            return {
                "cypher": combined[key],
                "params": _build_params(a, id_a_val, b, id_b_val),
                "key": key,
            }
    return None
