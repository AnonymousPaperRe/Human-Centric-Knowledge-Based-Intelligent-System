from neomodel import StructuredNode, StringProperty, RelationshipTo, DateTimeFormatProperty, IntegerProperty, StructuredRel, FloatProperty, DateProperty, DateTimeProperty
from newDigitalThreadLayer import currentVer, pastVer

class qualifiedToProduce(StructuredRel):
    pass

class instanceOf(StructuredRel):
    pass

class assignedTo(StructuredRel):
    pass

class hasShop(StructuredRel):
    pass

class createsPlan(StructuredRel):
    pass

class ManufacturingPlant(StructuredNode):
    name = StringProperty()
    identifier = StringProperty()
    location = StringProperty()          # FIX B1: replaced wrong 'power'/'trim'
    country = StringProperty()           # FIX B1: replaced wrong 'trim'
    hasshop = RelationshipTo('ProductionShop', 'HAS_SHOP', model = hasShop)  # FIX B2: 'hasPart' → 'hasShop'
    createsplan = RelationshipTo('ProductionPlan', 'CREATES_PLAN', model = createsPlan)

class ProductionShop(StructuredNode):
    name = StringProperty()
    identifier = StringProperty()
    type = StringProperty()
    qualifiedtoproduce = RelationshipTo('ProductDesignLayer.VehicleVariant', 'QUALIFIED_PRODUCE', model = qualifiedToProduce)  # FIX B4: added module prefix
    # hascell = RelationshipTo('WorkCell', 'hasCell', model = hasCell)  # FIX B3: 'hasPart' → 'hasCell'

class AssemblyShop(ProductionShop):
    type = "Assembly"

class PaintShop(ProductionShop):
    type = "Paint"

class BodyShop(ProductionShop):
    type = "Body"

class ProductionPlan(StructuredNode):
    name = StringProperty()
    identifier = StringProperty()
    current_version  = StringProperty(required=True)
    current_status = StringProperty(required=True)
    currentver = RelationshipTo('newDigitalThreadLayer.ProductionPlanVersion', 'CURRENT_VERSION', model = currentVer)
    pastver = RelationshipTo('newDigitalThreadLayer.ProductionPlanVersion', 'PAST_VERSION', model = pastVer)    

class ProductionOrder(StructuredNode):
    name = StringProperty()
    identifier = StringProperty()
    current_version  = StringProperty(required=True)
    current_status = StringProperty(required=True)
    assignedto = RelationshipTo("ManufacturingPlant", "ASSIGNED_TO", model = assignedTo)
    currentver = RelationshipTo('newDigitalThreadLayer.ProductionOrderVersion', 'CURRENT_VERSION', model = currentVer)
    pastver = RelationshipTo('newDigitalThreadLayer.ProductionOrderVersion', 'PAST_VERSION', model = pastVer)  

# class WorkCell(StructuredNode):
#     name = StringProperty()
#     identifier = StringProperty()
#     hasstoragearea = RelationshipTo('LogisticsLayer.WorkCellStorageArea', 'hasStorageArea', model = hasStorageArea)  # ADD R4