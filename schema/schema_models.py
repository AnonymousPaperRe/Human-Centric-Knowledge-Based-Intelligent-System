from neomodel import (
    StructuredNode,
    StringProperty,
    BooleanProperty,
    DateTimeFormatProperty,
    RelationshipTo,
)


class SchemaProperty(StructuredNode):
    name = StringProperty(required=True)
    dataType = StringProperty()        # string / int / float / datetime / bool
    required = BooleanProperty(default=False)
    defaultValue = StringProperty()


class SchemaRelationship(StructuredNode):
    name = StringProperty(required=True)
    relationshipType = StringProperty()   # NEO4J relationship type (CAPS)
    toNodeName = StringProperty()         # target SchemaNode name
    cardinality = StringProperty()        # ONE_TO_ONE / ONE_TO_MANY / MANY_TO_ONE


class SchemaNode(StructuredNode):
    name = StringProperty(unique_index=True, required=True)
    baseClass = StringProperty()          # "Specification" or "State"
    layer = StringProperty()              # which .py file it belongs to
    isAbstract = BooleanProperty(default=False)
    version = StringProperty(default="1.0")
    createdAt = DateTimeFormatProperty(format="%Y-%m-%d %H:%M:%S")

    properties = RelationshipTo("schema.schema_models.SchemaProperty", "HAS_PROPERTY")
    relationships = RelationshipTo("schema.schema_models.SchemaRelationship", "HAS_RELATIONSHIP")
