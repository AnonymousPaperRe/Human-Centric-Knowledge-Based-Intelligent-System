from neomodel import StructuredNode, StringProperty, RelationshipTo, RelationshipFrom, IntegerProperty, StructuredRel, FloatProperty, DateProperty, DateTimeProperty, DateTimeFormatProperty
from newDigitalThreadLayer import hasState

class realizesPlan(StructuredRel):
    pass

class suppliedBy(StructuredRel):
    pass

class occursAt(StructuredRel):
    pass

class hasTask(StructuredRel):
    pass

class producesVehicle(StructuredRel):
    pass

class hasParticipant(StructuredRel):
    pass

class usesEquipment(StructuredRel):
    pass

class usesTool(StructuredRel):
    pass

class consumesPart(StructuredRel):
    quantity = IntegerProperty()

class configuredTo(StructuredRel):
    pass

class instantiatesOperation(StructuredRel): # ADD R1
    pass

class instanceOf(StructuredRel):
    pass

class Personnel(StructuredNode):
    name = StringProperty()
    identifier = StringProperty()
    role = StringProperty()             # ADD: e.g. "operator", "inspector", "supervisor"
    hasstate = RelationshipTo('newDigitalThreadLayer.PersonnelState', 'HAS_STATE', model = hasState)

class PartInstance(StructuredNode):
    name = StringProperty()
    partid = StringProperty()           # ERP/SAP part number
    conformsto = RelationshipTo('ProcessPlanLayer.Part', 'INSTANCE_OF', model = instanceOf)
    configuredto = RelationshipTo('newDigitalThreadLayer.PartSpecification', 'CONFIGURED_TO', model = configuredTo)
    suppliedby = RelationshipTo('ProcessPlanLayer.Supplier', 'SUPPLIED_BY', model = suppliedBy)


class PartBatch(PartInstance):
    batchNumber = StringProperty(unique_index=True, required=True)        # identifier: lot/batch number
    # This represents a physical box/batch from a supplier
    # identifier = StringProperty(unique_index=True, required=True) # e.g., "BATCH-A123"
    # We only care about statuses that affect PRODUCTION (not location)
    # HOLD = Quality inspection failed, do not use!
    # status = StringProperty(choices={'AVAILABLE': 'Available', 'DEPLETED': 'Depleted', 'HOLD': 'Quality Hold'})
    initialQuantity = IntegerProperty()
    receiveTime = DateTimeFormatProperty(format="%Y-%m-%d %H:%M:%S")

class PartSerial(PartInstance):
    serialNumber = StringProperty()     # identifier: unique serial for this instance

class ToolInstance(StructuredNode):
    name = StringProperty()
    identifier = StringProperty()
    serialNumber = StringProperty()     # ADD: equipment serial number
    conformsto = RelationshipTo('ProcessPlanLayer.Tool', 'INSTANCE_OF', model = instanceOf)
    configuredto = RelationshipTo('newDigitalThreadLayer.ToolSpecification', 'CONFIGURED_TO', model = configuredTo)

class ManualToolInstance(ToolInstance):
    conformsto =  RelationshipTo('ProcessPlanLayer.ManualTool', 'INSTANCE_OF', model = instanceOf)
    configuredto = RelationshipTo('newDigitalThreadLayer.ManualToolSpecification', 'CONFIGURED_TO', model = configuredTo)

class PrecisionToolInstance(ToolInstance):
    torque = StringProperty()
    conformsto =  RelationshipTo('ProcessPlanLayer.PrecisionTool', 'INSTANCE_OF', model = instanceOf)
    configuredto = RelationshipTo('newDigitalThreadLayer.PrecisionToolSpecification', 'CONFIGURED_TO', model = configuredTo)

class EquipmentInstance(StructuredNode):
    name = StringProperty()
    identifier = StringProperty()
    serialNumber = StringProperty()     # ADD: equipment serial number
    conformsto = RelationshipTo('ProcessPlanLayer.Equipment', 'INSTANCE_OF', model = instanceOf)
    hasstate = RelationshipTo('newDigitalThreadLayer.EquipmentState', 'hasState', model = hasState)
    configuredto = RelationshipTo('newDigitalThreadLayer.EquipmentSpecification', 'CONFIGURED_TO', model = configuredTo)

class RoboticEquipmentInstance(EquipmentInstance):
    conformsto =  RelationshipTo('ProcessPlanLayer.RoboticEquipment', 'INSTANCE_OF', model = instanceOf)
    configuredto = RelationshipTo('newDigitalThreadLayer.RoboticEquipmentSpecification', 'CONFIGURED_TO', model = configuredTo)

class ProcessEquipmentInstance(EquipmentInstance):
    conformsto =  RelationshipTo('ProcessPlanLayer.ProcessEquipment', 'INSTANCE_OF', model = instanceOf)
    configuredto = RelationshipTo('newDigitalThreadLayer.ProcessEquipmentSpecification', 'CONFIGURED_TO', model = configuredTo)

class DiagnosticEquipmentInstance(EquipmentInstance):
    conformsto =  RelationshipTo('ProcessPlanLayer.DiagnosticEquipment', 'INSTANCE_OF', model = instanceOf)
    configuredto = RelationshipTo('newDigitalThreadLayer.DiagnosticEquipmentSpecification', 'CONFIGURED_TO', model = configuredTo)

class MaterialHandlingEquipmentInstance(EquipmentInstance):
    conformsto =  RelationshipTo('ProcessPlanLayer.MaterialHandlingEquipment', 'INSTANCE_OF', model = instanceOf)
    configuredto = RelationshipTo('newDigitalThreadLayer.MaterialHandlingEquipmentSpecification', 'CONFIGURED_TO', model = configuredTo)

class OperationalTask(StructuredNode):
    name = StringProperty()
    identifier = StringProperty()
    startTime = DateTimeFormatProperty(format="%Y-%m-%d %H:%M:%S")
    endTime = DateTimeFormatProperty(format="%Y-%m-%d %H:%M:%S")
    hasparticipant = RelationshipTo('Personnel', 'HAS_PARTICIPANT', model = hasParticipant)
    usesequipment = RelationshipTo('EquipmentInstance', 'USE_EQUIPMENT', model = usesEquipment)
    usestool = RelationshipTo('ToolInstance', 'USE_TOOL', model = usesTool)
    consumespart = RelationshipTo('PartInstance', 'CONSUMES_PART', model = consumesPart)
    instantiates = RelationshipTo('newDigitalThreadLayer.OperationVersion', 'INSTANTIATES_OPERATION', model = instantiatesOperation)  # ADD R1

YIELD_STATES = {
        'SHORTFALL': 'Below Target (Under Production)',
        'EXACT': 'Equal to Target',
        'OVERAGE': 'Over Production'
    }

class ProductionProcess(StructuredNode):
    name = StringProperty()
    identifier = StringProperty()
    startTime = DateTimeFormatProperty(format="%Y-%m-%d %H:%M:%S")
    endTime = DateTimeFormatProperty(format="%Y-%m-%d %H:%M:%S")
    targetQuantity = IntegerProperty(required=True)     # What was the plan?
    qualifiedQuantity = IntegerProperty(default=0)      # Good parts produced
    result = StringProperty(choices = YIELD_STATES)
    realizesplan = RelationshipTo('newDigitalThreadLayer.ProductionPlanVersion', 'REALIZES_PLAN', model = realizesPlan)
    occursat = RelationshipTo("PlantOrganizationLayer.ProductionShop", "OCCURS_AT", model = occursAt)
    producesvehicle = RelationshipTo("Vehicle", "PRODUCES_VEHICLE", model = producesVehicle)
    hastask = RelationshipTo("OperationalTask", "HAS_TASK", model = hasTask)
    hasstate = RelationshipTo('newDigitalThreadLayer.ProductionProcessState', 'HAS_STATE', model = hasState)

class Vehicle(StructuredNode):
    name = StringProperty()
    identifier = StringProperty()  # vin 
    # vin = StringProperty()              # ADD: Vehicle Identification Number — primary automotive key
    # color = StringProperty()            # ADD: exterior color code
    producedTime = DateTimeFormatProperty(format="%Y-%m-%d %H:%M:%S") 
    # 1. The High-Level Entity Link (For fast counting/aggregation)
    instanceof = RelationshipTo('ProductDesignLayer.VehicleVariant', 'INSTANCE_OF', model = instanceOf)
    # 2. The Deep Engineering Link (For BOM traceability and ECOs)
    configuredto = RelationshipTo('newDigitalThreadLayer.VehicleVariantSpecification', 'CONFIGURED_TO', model = configuredTo)