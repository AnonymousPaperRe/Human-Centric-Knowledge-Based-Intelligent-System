from neomodel import StructuredNode, StringProperty, RelationshipTo, DateTimeFormatProperty, IntegerProperty, StructuredRel, FloatProperty, DateProperty, DateTimeProperty
from newDigitalThreadLayer import currentSpec, pastSpec, currentVer, pastVer

class hasVariant(StructuredRel):
    pass

class describedIn(StructuredRel):
    pass

class ProductDocument(StructuredNode):
    name = StringProperty(required=True)
    identifier = StringProperty(unique_index=True, required=True)
    current_version  = StringProperty(required=True)
    current_status = StringProperty(required=True)
    currentver = RelationshipTo('newDigitalThreadLayer.ProductDocumentVersion', 'CURRENT_VERSION', model = currentVer)
    pastver = RelationshipTo('newDigitalThreadLayer.ProductDocumentVersion', 'PAST_VERSION', model = pastVer)  

class VehicleVariant(StructuredNode):
    name = StringProperty()
    identifier = StringProperty()
    current_version  = StringProperty(required=True)
    current_status = StringProperty(required=True) 
    # status = StringProperty()           # design, production, stop production 
    power = StringProperty()            # powertrain type: EV / ICE / HEV / PHEV
    trim = StringProperty()             # trim level: Base / Sport / Premium
    engine = StringProperty()           # ADD: engine code e.g. "EA888"
    transmission = StringProperty()     # ADD: e.g. "DSG7", "Manual6"
    currentspec = RelationshipTo('newDigitalThreadLayer.VehicleVariantSpecification', 'CURRENT_SPECIFICATION', model = currentSpec)
    pastspec = RelationshipTo('newDigitalThreadLayer.VehicleVariantSpecification', 'PAST_SPECIFICATION', model = pastSpec) 

class VehicleFamily(StructuredNode):
    name = StringProperty()
    identifier = StringProperty()
    hasvariant = RelationshipTo('VehicleVariant', 'HAS_VARIANT', model = hasVariant)
    describedin = RelationshipTo('ProductDocument', 'DESCRIBED_IN', model = describedIn)


