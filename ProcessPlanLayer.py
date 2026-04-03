from neomodel import StructuredNode, StringProperty, RelationshipTo, RelationshipFrom, IntegerProperty, StructuredRel, FloatProperty, DateProperty, DateTimeProperty, DateTimeFormatProperty
from newDigitalThreadLayer import currentSpec, pastSpec, currentVer, pastVer, hasState

class qualifiedFor(StructuredRel):      # FIX B5: was qualidiedFor
    pass

class Part(StructuredNode):
    name = StringProperty(required=True)
    identifier = StringProperty(unique_index=True, required=True)
    current_status  = StringProperty(required=True)
    current_version = StringProperty()
    currentspec = RelationshipTo('newDigitalThreadLayer.PartSpecification', 'CURRENT_SPECIFICATION', model = currentSpec)
    pastspec = RelationshipTo('newDigitalThreadLayer.PartSpecification', 'PAST_SPECIFICATION', model = pastSpec)

class Tool(StructuredNode):
    name = StringProperty(required=True)
    identifier = StringProperty(unique_index=True, required=True)
    current_status = StringProperty(required=True)
    current_version = StringProperty()
    currentspec = RelationshipTo('newDigitalThreadLayer.ToolSpecification', 'CURRENT_SPECIFICATION', model = currentSpec)
    pastspec = RelationshipTo('newDigitalThreadLayer.ToolSpecification', 'PAST_SPECIFICATION', model = pastSpec)  
    # equipmentType = StringProperty()    # ADD: e.g. "PrecisionTool", "ProcessEquipment", "ManualTool", "FixtureSystem", "MaterialHandlingEquipment, "TestingEquipment", "RoboticSystem"
    # manufacturer = StringProperty()     # ADD
    # model = StringProperty()            # ADD: model/product number
    # hasspecification = RelationshipTo('newDigitalThreadLayer.EquipmentSpec', 'hasSpecification', model = hasSpecification)

class ManualTool(Tool):
    currentspec = RelationshipTo('newDigitalThreadLayer.ManualToolSpecification', 'CURRENT_SPECIFICATION', model = currentSpec)
    pastspec = RelationshipTo('newDigitalThreadLayer.ManualToolSpecification', 'PAST_SPECIFICATION', model = pastSpec)  
    # quota = FloatProperty()

class PrecisionTool(Tool):
    currentspec = RelationshipTo('newDigitalThreadLayer.PrecisionToolSpecification', 'CURRENT_SPECIFICATION', model = currentSpec)
    pastspec = RelationshipTo('newDigitalThreadLayer.PrecisionToolSpecification', 'PAST_SPECIFICATION', model = pastSpec)  
    # torque = StringProperty()
    # quota = FloatProperty()

class Equipment(StructuredNode):
    name = StringProperty(required=True)
    identifier = StringProperty(unique_index=True, required=True)
    current_status = StringProperty(required=True)
    current_version = StringProperty()
    currentspec = RelationshipTo('newDigitalThreadLayer.EquipmentSpecification', 'CURRENT_SPECIFICATION', model = currentSpec)
    pastspec = RelationshipTo('newDigitalThreadLayer.EquipmentSpecification', 'PAST_SPECIFICATION', model = pastSpec)  
    # equipmentType = StringProperty()    # ADD: e.g. "PrecisionTool", "ProcessEquipment", "ManualTool", "FixtureSystem", "MaterialHandlingEquipment, "TestingEquipment", "RoboticSystem"
    # manufacturer = StringProperty()     # ADD
    # model = StringProperty()            # ADD: model/product number

class RoboticEquipment(Equipment):
    currentspec = RelationshipTo('newDigitalThreadLayer.RoboticEquipmentSpecification', 'CURRENT_SPECIFICATION', model = currentSpec)
    pastspec = RelationshipTo('newDigitalThreadLayer.RoboticEquipmentSpecification', 'PAST_SPECIFICATION', model = pastSpec)  

class ProcessEquipment(Equipment):
    currentspec = RelationshipTo('newDigitalThreadLayer.ProcessEquipmentSpecification', 'CURRENT_SPECIFICATION', model = currentSpec)
    pastspec = RelationshipTo('newDigitalThreadLayer.ProcessEquipmentSpecification', 'PAST_SPECIFICATION', model = pastSpec)  

class DiagnosticEquipment(Equipment):
    currentspec = RelationshipTo('newDigitalThreadLayer.DiagnosticEquipmentSpecification', 'CURRENT_SPECIFICATION', model = currentSpec)
    pastspec = RelationshipTo('newDigitalThreadLayer.DiagnosticEquipmentSpecification', 'PAST_SPECIFICATION', model = pastSpec)  

class MaterialHandlingEquipment(Equipment):
    currentspec = RelationshipTo('newDigitalThreadLayer.MaterialHandlingEquipmentSpecification', 'CURRENT_SPECIFICATION', model = currentSpec)
    pastspec = RelationshipTo('newDigitalThreadLayer.MaterialHandlingEquipmentSpecification', 'PAST_SPECIFICATION', model = pastSpec)  

# class WorkStep(StructuredNode):
#     name = StringProperty(required=True)
#     identifier = StringProperty(unique_index=True, required=True)
#     current_version  = StringProperty(required=True)
#     current_status = StringProperty(required=True)
#     currentver = RelationshipTo('newDigitalThreadLayer.WorkStepVersion', 'CURRENT_VERSION', model = currentVer)
#     pastver = RelationshipTo('newDigitalThreadLayer.WorkStepVersion', 'PAST_VERSION', model = pastVer)  

class Operation(StructuredNode):
    name = StringProperty(required=True)
    identifier = StringProperty(unique_index=True, required=True)
    current_version  = StringProperty(required=True)
    current_status = StringProperty(required=True)
    qualifiedfor = RelationshipTo('PlantOrganizationLayer.ProductionShop', 'QUALIFIED_FOR', model = qualifiedFor)  # FIX B5
    currentver = RelationshipTo('newDigitalThreadLayer.OperationVersion', 'CURRENT_VERSION', model = currentVer)
    pastver = RelationshipTo('newDigitalThreadLayer.OperationVersion', 'PAST_VERSION', model = pastVer)  

class Supplier(StructuredNode):
    name = StringProperty()
    identifier = StringProperty()