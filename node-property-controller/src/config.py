import os

GROUP_DEFAULT = "policydriven.unimi.it"
VERSION_DEFAULT = "v1alpha1"
PLURAL_DEFAULT = "nodeproperties"
ATTRIBUTE_PREFIX_DEFAULT = "attribute.node.policydriven.unimi.it"
PROPERTY_PREFIX_DEFAULT = "property.node.policydriven.unimi.it"


class Config:
    """Service configuration loaded from environment variables."""

    def __init__(
        self,
        group: str,
        version: str,
        plural: str,
        attribute_prefix: str,
        property_prefix: str,
        log_level: str,
    ):
        self.group = group
        self.version = version
        self.plural = plural
        self.attribute_prefix = attribute_prefix
        self.property_prefix = property_prefix
        self.log_level = log_level

    @staticmethod
    def from_env() -> "Config":
        return Config(
            group=os.getenv("GROUP", GROUP_DEFAULT),
            version=os.getenv("VERSION", VERSION_DEFAULT),
            plural=os.getenv("PLURAL", PLURAL_DEFAULT),
            attribute_prefix=os.getenv("ATTRIBUTE_PREFIX", ATTRIBUTE_PREFIX_DEFAULT),
            property_prefix=os.getenv("PROPERTY_PREFIX", PROPERTY_PREFIX_DEFAULT),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )
