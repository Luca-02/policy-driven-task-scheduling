import os

GROUP_DEFAULT = "policydriven.unimi.it"
VERSION_DEFAULT = "v1alpha1"
NODE_PROPERTIES_PLURAL_DEFAULT = "nodeproperties"
ATTRIBUTE_PREFIX_DEFAULT = f"attribute.node.{GROUP_DEFAULT}"
PROPERTY_PREFIX_DEFAULT = f"property.node.{GROUP_DEFAULT}"


class Config:
    """Service configuration loaded from environment variables."""

    def __init__(
        self,
        group: str,
        version: str,
        node_properties_plural: str,
        attribute_prefix: str,
        property_prefix: str,
        log_level: str,
    ):
        self.group = group
        self.version = version
        self.node_properties_plural = node_properties_plural
        self.attribute_prefix = attribute_prefix
        self.property_prefix = property_prefix
        self.log_level = log_level

    @staticmethod
    def from_env() -> "Config":
        return Config(
            group=os.getenv("GROUP", GROUP_DEFAULT),
            version=os.getenv("VERSION", VERSION_DEFAULT),
            node_properties_plural=os.getenv("NODE_PROPERTIES_PLURAL", NODE_PROPERTIES_PLURAL_DEFAULT),
            attribute_prefix=os.getenv("ATTRIBUTE_PREFIX", ATTRIBUTE_PREFIX_DEFAULT),
            property_prefix=os.getenv("PROPERTY_PREFIX", PROPERTY_PREFIX_DEFAULT),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )
