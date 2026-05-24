import os

from dotenv import load_dotenv


class Config:
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
        load_dotenv()
        return Config(
            group=os.getenv("GROUP", "nodeclass.io"),
            version=os.getenv("VERSION", "v1alpha1"),
            plural=os.getenv("PLURAL", "node-property-definitions"),
            attribute_prefix=os.getenv("ATTRIBUTE_PREFIX", "attribute.node.nodeclass.io"),
            property_prefix=os.getenv("PROPERTY_PREFIX", "property.node.nodeclass.io"),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )
