import os


class Config:
    """Service configuration, loaded from environment variables."""

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
            group=os.getenv("GROUP", "policydriven.unimi.it"),
            version=os.getenv("VERSION", "v1alpha1"),
            plural=os.getenv("PLURAL", "nodeproperties"),
            attribute_prefix=os.getenv(
                "ATTRIBUTE_PREFIX", "attribute.node.policydriven.unimi.it"
            ),
            property_prefix=os.getenv(
                "PROPERTY_PREFIX", "property.node.policydriven.unimi.it"
            ),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )
