from neomodel import (
    StructuredNode,
    StringProperty,
    RelationshipTo,
    DateTimeFormatProperty,
    IntegerProperty,
    BooleanProperty,
    StructuredRel,
)

# --- 1. Custom Edge Properties (Excellent use of StructuredRel here!) ---

class hasAction(StructuredRel):
    sequence = IntegerProperty()

class affectsOld(StructuredRel):
    reason = StringProperty()

class affectsNew(StructuredRel):
    reason = StringProperty()

class impactsVersion(StructuredRel):
    impactType = StringProperty()  # DIRECT / INDIRECT
    reason = StringProperty()
    severity = StringProperty()  # LOW / MEDIUM / HIGH / CRITICAL
    requiredBy = DateTimeFormatProperty(format="%Y-%m-%d %H:%M:%S")
    resolved = BooleanProperty(default=False)

class impactsSpecification(StructuredRel):
    impactType = StringProperty()  # DIRECT / INDIRECT
    reason = StringProperty()
    severity = StringProperty()  # LOW / MEDIUM / HIGH / CRITICAL
    requiredBy = DateTimeFormatProperty(format="%Y-%m-%d %H:%M:%S")
    resolved = BooleanProperty(default=False)

class impactsProcess(StructuredRel):
    impactType = StringProperty()  # DIRECT / INDIRECT
    reason = StringProperty()
    severity = StringProperty()  # LOW / MEDIUM / HIGH / CRITICAL
    requiredBy = DateTimeFormatProperty(format="%Y-%m-%d %H:%M:%S")
    holdRequired = BooleanProperty(default=False)
    resolved = BooleanProperty(default=False)
    notes = StringProperty()  

class impactsMaterial(StructuredRel):
    impactType = StringProperty()  # DIRECT / INDIRECT
    reason = StringProperty()
    severity = StringProperty()  # LOW / MEDIUM / HIGH / CRITICAL
    requiredBy = DateTimeFormatProperty(format="%Y-%m-%d %H:%M:%S")
    holdRequired = BooleanProperty(default=False)
    resolved = BooleanProperty(default=False)
    notes = StringProperty()  


class causedBy(StructuredRel):
    sourceType = StringProperty()  # DESIGN_CHANGE / SUPPLIER_CHANGE / QUALITY_ISSUE / REGULATORY

class supersedesAction(StructuredRel):
    reason = StringProperty()

class hasEffectivity(StructuredRel):
    mandatory = BooleanProperty(default=True)


# --- 2. The Nodes ---

class EffectivityScope(StructuredNode):
    identifier = StringProperty(unique_index=True, required=True)
    scopeType = StringProperty()  # GLOBAL / PLANT / SHOP / CELL / VARIANT / ORDER / DATE_WINDOW
    scopeValue = StringProperty()  # business key/value for quick filtering
    validFrom = DateTimeFormatProperty(format="%Y-%m-%d %H:%M:%S")
    validTo = DateTimeFormatProperty(format="%Y-%m-%d %H:%M:%S")
    notes = StringProperty()

    toplant = RelationshipTo("PlantOrganizationLayer.ManufacturingPlant", "EFFECTIVE_AT_PLANT")
    toshop = RelationshipTo("PlantOrganizationLayer.ProductionShop", "EFFECTIVE_AT_SHOP")
    tovariant = RelationshipTo("ProductDesignLayer.VehicleVariant", "EFFECTIVE_FOR_VARIANT")


class ChangeSet(StructuredNode):
    identifier = StringProperty(unique_index=True, required=True)
    title = StringProperty(required=True)
    changeType = StringProperty()  # DESIGN / PROCESS / SUPPLIER / EQUIPMENT / PLANNING
    status = StringProperty()  # PROPOSED / UNDER_REVIEW / APPROVED / IMPLEMENTED / CANCELED
    owner = StringProperty()
    ownerOrg = StringProperty()
    priority = StringProperty()  # LOW / MEDIUM / HIGH / URGENT
    riskLevel = StringProperty()  # LOW / MEDIUM / HIGH / CRITICAL
    requestTime = DateTimeFormatProperty(format="%Y-%m-%d %H:%M:%S")
    effectiveTime = DateTimeFormatProperty(format="%Y-%m-%d %H:%M:%S")
    closeTime = DateTimeFormatProperty(format="%Y-%m-%d %H:%M:%S")
    notes = StringProperty()

    hasaction = RelationshipTo("ChangeAction", "HAS_ACTION", model=hasAction)
    
    # Recursive relationship between parent and child change sets.
    parentchange = RelationshipTo("ChangeSet", "PARENT_CHANGE") 


class ChangeAction(StructuredNode):
    identifier = StringProperty(unique_index=True, required=True)
    actionType = StringProperty(required=True)
    status = StringProperty()  # PLANNED / IN_PROGRESS / DONE / REJECTED / ON_HOLD
    reason = StringProperty()
    sequence = IntegerProperty()
    createTime = DateTimeFormatProperty(format="%Y-%m-%d %H:%M:%S")
    targetCompletion = DateTimeFormatProperty(format="%Y-%m-%d %H:%M:%S")

# --- 1. The Engineering Pointers (Specifications) ---
    # For updating PartSpec, EquipmentSpec, VehicleVariantSpec
    affectsoldspec = RelationshipTo("newDigitalThreadLayer.Specification", "AFFECTS_OLD_SPEC", model=affectsOld)
    affectsnewspec = RelationshipTo("newDigitalThreadLayer.Specification", "AFFECTS_NEW_SPEC", model=affectsNew)

    # --- 2. The Engineering Pointers (Versions) ---
    # ADDED: For updating OperationVersion, WorkStepVersion, ProductionPlanVersion
    affectsoldversion = RelationshipTo("newDigitalThreadLayer.Version", "AFFECTS_OLD_VERSION", model=affectsOld)
    affectsnewversion = RelationshipTo("newDigitalThreadLayer.Version", "AFFECTS_NEW_VERSION", model=affectsNew)

    # FIX: Updated all target classes to match our finalized Digital Thread naming convention
    # --- Version ---
    # impactsworkstepversion = RelationshipTo("newDigitalThreadLayer.WorkStepVersion", "IMPACTS_WORKSTEP_VERSION", model=impactsVersion)
    impactsoperationversion = RelationshipTo("newDigitalThreadLayer.OperationVersion", "IMPACTS_OPERATION_VERSION", model=impactsVersion)
    impactsproductdocumentversion = RelationshipTo("newDigitalThreadLayer.ProductDocumentVersion", "IMPACTS_PRODUCTDOCUMENT_VERSION", model=impactsVersion)
    impactproductionorderversion = RelationshipTo("newDigitalThreadLayer.ProductionOrderVersion", "IMPACTS_PRODUCTIONORDER_VERSION", model=impactsVersion)
    impactproductionplanversion = RelationshipTo("newDigitalThreadLayer.ProductionPlanVersion", "IMPACTS_PRODUCTIONPLAN_VERSION", model=impactsVersion)

    # --- Specification ---
    impactsvehiclevariant = RelationshipTo("newDigitalThreadLayer.VehicleVariantSpecification", "IMPACTS_VEHICLEVARIANT_SPEC", model=impactsSpecification)
    impactspartspec = RelationshipTo("newDigitalThreadLayer.PartSpecification", "IMPACTS_PART_SPEC", model=impactsSpecification)
    impacttoolspec = RelationshipTo("newDigitalThreadLayer.ToolSpecification", "IMPACTS_TOOL_SPEC", model=impactsSpecification)
    impactsequipspec = RelationshipTo("newDigitalThreadLayer.EquipmentSpecification", "IMPACTS_EQUIPMENT_SPEC", model=impactsSpecification)

    # --- Material / instance impacts ---
    impactsprocess = RelationshipTo("ProductionProcessLayer.ProductionProcess", "IMPACTS_PROCESS", model=impactsProcess)
    impactstask = RelationshipTo("ProductionProcessLayer.OperationalTask", "IMPACTS_TASK", model=impactsProcess)

    # --- Process ---
    impactspartinstance = RelationshipTo("ProductionProcessLayer.PartInstance", "IMPACTS_PART_INSTANCE", model=impactsMaterial)
    impactsequipmentinstance = RelationshipTo("ProductionProcessLayer.EquipmentInstance", "IMPACTS_EQUIPMENT_INSTANCE", model=impactsMaterial)
    impactstoolinstance = RelationshipTo("ProductionProcessLayer.ToolInstance", "IMPACTS_TOOL_INSTANCE", model=impactsMaterial)
    impactsvehicle = RelationshipTo("ProductionProcessLayer.Vehicle", "IMPACTS_VEHICLE", model=impactsMaterial)
    impactspersonnel = RelationshipTo("ProductionProcessLayer.Personnel", "IMPACTS_PERSONNEL", model=impactsMaterial)

    # --- Metadata Pointers ---
    haseffectivity = RelationshipTo("EffectivityScope", "HAS_EFFECTIVITY", model=hasEffectivity)
    causedby = RelationshipTo("ChangeSet", "CAUSED_BY", model=causedBy)
    
    # Recursive action lineage.
    supersedesaction = RelationshipTo("ChangeAction", "SUPERSEDES_ACTION", model=supersedesAction)
