NAMESPACES_INTERNAL = ["Internal", "Profile", "Template"]

schema_attribute_type_mapping = {
    "Text": "String",
    "Number": "Integer",
    "Boolean": "Boolean",
    "DateTime": "DateTime",
    "Enum": "String",
}

_ALLOWED_PLACEHOLDERS = {"date", "hex", "user"}

AUTH_MODE_NONE = "none"
AUTH_MODE_OIDC = "oidc"
_VALID_AUTH_MODES = {AUTH_MODE_NONE, AUTH_MODE_OIDC}
