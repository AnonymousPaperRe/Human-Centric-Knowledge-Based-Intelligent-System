from neomodel import (
    StructuredNode,
    StringProperty,
    RelationshipTo,
    DateTimeFormatProperty,
    IntegerProperty,
    StructuredRel,
    BooleanProperty,
    FloatProperty
)

VERSION_STATES = {
    'PENDING': 'Pending / Approved for Future',
    'ACTIVE': 'Currently Active',
    'SUPERSEDED': 'Superseded by Newer Version',
    'OBSOLETE': 'Obsolete / End of Life'
}

SPEC_STATES = {
    'PENDING': 'Pending / Approved for Future',
    'ACTIVE': 'Currently Active',
    'SUPERSEDED': 'Superseded by Newer Revision',
    'OBSOLETE': 'Obsolete / End of Life'
}

class hasSupplier(StructuredRel):
    pass

class plansForVariant(StructuredRel):
    quantity = IntegerProperty(required=True)

class ordersVariant(StructuredRel):
    quantity = IntegerProperty(required=True)

class hasState(StructuredRel):
    pass

class instantiatesPlan(StructuredRel):
    pass

class currentSpec(StructuredRel):
    pass

class pastSpec(StructuredRel):
    pass

class currentVer(StructuredRel):
    pass

class pastVer(StructuredRel):
    pass

class supersedes(StructuredRel):
    pass

class derivedFrom(StructuredRel):
    pass

class hasStep(StructuredRel):
    pass

class requiresPart(StructuredRel):
    quantity = IntegerProperty()
    optionalcode = StringProperty()

class requiresEquipment(StructuredRel):
    pass

class requiresTool(StructuredRel):
    pass

class applicableAt(StructuredRel):
    pass

class applicableTo(StructuredRel):
    pass

class hasBOMItem(StructuredRel):
    identifier = StringProperty()       # VWS BOM item ID
    quantity = IntegerProperty()
    createTime = DateTimeFormatProperty(format="%Y-%m-%d %H:%M:%S")
    validFrom = DateTimeFormatProperty(format="%Y-%m-%d %H:%M:%S")
    validTo = DateTimeFormatProperty(format="%Y-%m-%d %H:%M:%S")
    status = StringProperty(choices=SPEC_STATES)
    optionalcode = StringProperty()
    optionalpackage = StringProperty()

# Define your allowed lifecycle states


class Version(StructuredNode):
    name = StringProperty()
    identifier = StringProperty(unique_index=True, required=True)
    version = StringProperty(required=True)
    status = StringProperty(choices=VERSION_STATES, required=True)
    createTime = DateTimeFormatProperty(format="%Y-%m-%d %H:%M:%S")
    validFrom = DateTimeFormatProperty(format="%Y-%m-%d %H:%M:%S")
    validTo = DateTimeFormatProperty(format="%Y-%m-%d %H:%M:%S")
    source = StringProperty()  # engineering/system source of truth
    sourceDoc = StringProperty()  # drawing/doc/SW baseline identifier
    notes = StringProperty()
    supersedes_rel = RelationshipTo('Version', 'SUPERSEDES_VERSION', model = supersedes) 

class ProductDocumentVersion(Version):
    pass

# class WorkStepVersion(Version):
#     instruction = StringProperty()      # ADD: the actual work instruction text
#     estimatedDuration = FloatProperty() # ADD: second
#     sequence = IntegerProperty()  # ADD: order within its operation # no sequence number for workstepspecification
#     derivedfrom = RelationshipTo('ProductDocumentVersion', 'DERIVED_FROM', model = derivedFrom)

class OperationVersion(Version):
    hasLocation = StringProperty()
    estimatedDuration = FloatProperty()
    sequence = IntegerProperty()
    # hasstep = RelationshipTo('WorkStepVersion', 'HAS_STEP', model = hasStep)
    requirespart = RelationshipTo('PartSpecification', 'REQUIRES_PART', model = requiresPart)
    requiresequipment = RelationshipTo('EquipmentSpecification', 'REQUIRES_EQUIPMENT', model = requiresEquipment)
    requiretool = RelationshipTo('ToolSpecification', 'REQUIRES_TOOL', model = requiresTool)
    applicableto = RelationshipTo('VehicleVariantSpecification', 'APPLICABLE_TO', model = applicableTo)
    derivedfrom = RelationshipTo('ProductDocumentVersion', 'DERIVED_FROM', model = derivedFrom)


class ProductionPlanVersion(Version):
    plannedStartTime = DateTimeFormatProperty(format="%Y-%m-%d %H:%M:%S")
    plannedEndTime = DateTimeFormatProperty(format="%Y-%m-%d %H:%M:%S")
    totalPlannedQuantity = IntegerProperty()
    plansforvariant = RelationshipTo('VehicleVariantSpecification', 'PLANS_VARIANT', model = plansForVariant)  # ADD R3

class ProductionOrderVersion(Version):
    plannedStartTime = DateTimeFormatProperty(format="%Y-%m-%d %H:%M:%S")
    plannedEndTime = DateTimeFormatProperty(format="%Y-%m-%d %H:%M:%S")
    totalPlannedQuantity = IntegerProperty()
    instantiatesplan = RelationshipTo("newDigitalThreadLayer.ProductionPlanVersion", "INSTANTIATES_PLAN", model = instantiatesPlan)
    ordersVariant = RelationshipTo('VehicleVariantSpecification', 'ORDERS_VARIANT', model = ordersVariant)

class Specification(StructuredNode):
    name = StringProperty()
    identifier = StringProperty(unique_index=True, required=True)
    # specType = StringProperty()  # product / operation / workstep / part / equipment / plan / order
    status = StringProperty(choices=SPEC_STATES, required=True)
    version = StringProperty()
    model = StringProperty()
    # revision = StringProperty()  # Used for parts, tools, equipment (e.g., "Rev B")
    createTime = DateTimeFormatProperty(format="%Y-%m-%d %H:%M:%S")
    validFrom = DateTimeFormatProperty(format="%Y-%m-%d %H:%M:%S")
    validTo = DateTimeFormatProperty(format="%Y-%m-%d %H:%M:%S")
    source = StringProperty()  # engineering/system source of truth
    sourceDoc = StringProperty()  # drawing/doc/SW baseline identifier
    notes = StringProperty()
    supersedes_rel = RelationshipTo('Specification', 'SUPERSEDES_SPECIFICATION', model = supersedes) 

class VehicleVariantSpecification(Specification):
    hasbomitem = RelationshipTo('PartSpecification', 'HAS_BOMITEM', model = hasBOMItem)

class PartSpecification(Specification):
    hassupplier = RelationshipTo('ProcessPlanLayer.Supplier', 'HAS_SUPPLIER', model = hasSupplier)

class ToolSpecification(Specification):
    quota = FloatProperty()

class ManualToolSpecification(ToolSpecification):
    pass

class PrecisionToolSpecification(ToolSpecification):
    torque = StringProperty()

class EquipmentSpecification(Specification):
    pass

class RoboticEquipmentSpecification(EquipmentSpecification):
    pass

class ProcessEquipmentSpecification(EquipmentSpecification):
    pass

class DiagnosticEquipmentSpecification(EquipmentSpecification):
    pass

class MaterialHandlingEquipmentSpecification(EquipmentSpecification):
    pass

class State(StructuredNode):
    identifier = StringProperty(unique_index=True, required=True)   
    # E.g., RUNNING, IDLE, FAULT, ON_SHIFT, OFF_SHIFT, IN_TRANSIT
    status = StringProperty(required=True) 
    createTime = DateTimeFormatProperty(format="%Y-%m-%d %H:%M:%S")
    validFrom = DateTimeFormatProperty(format="%Y-%m-%d %H:%M:%S", required=True)
    validTo = DateTimeFormatProperty(format="%Y-%m-%d %H:%M:%S")
    # Excellent addition for fast LLM querying
    isCurrent = BooleanProperty(default=True)
    notes = StringProperty()
    # States should also form a supersedes chain to trace the exact history!
    supersedes_rel = RelationshipTo('State', 'SUPERSEDES_STATE', model = supersedes)

class ProductionProcessState(State):
    pass
    # scrapQuantity = IntegerProperty(default=0)          # Bad/Rejected parts

class PersonnelState(State):
    pass

class EquipmentState(State):
    pass
