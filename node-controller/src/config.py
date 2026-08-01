import os

GROUP_DEFAULT = "policydriven.unimi.it"
VERSION_DEFAULT = "v1alpha1"
NODE_PROPERTIES_PLURAL_DEFAULT = "nodeproperties"
ATTRIBUTE_PREFIX_DEFAULT = f"attribute.node.{GROUP_DEFAULT}"
PROPERTY_PREFIX_DEFAULT = f"property.node.{GROUP_DEFAULT}"
TRACE_PREFIX_DEFAULT = f"trace.node.{GROUP_DEFAULT}"
CONTEXTS_ANNOTATION_DEFAULT = "contexts"
SANITIZING_TAINT_DEFAULT = "sanitizing"
SCHEDULER_NAME_DEFAULT = "policy-driven-scheduler"
SANITIZE_INTERVAL_SECONDS_DEFAULT = 60
CLEAR_TRACES_SIMULATION_SECONDS_DEFAULT = 0


class Config:
    """Service configuration loaded from environment variables."""

    def __init__(
        self,
        group: str,
        version: str,
        node_properties_plural: str,
        attribute_prefix: str,
        property_prefix: str,
        trace_prefix: str,
        contexts_annotation: str,
        sanitizing_taint: str,
        scheduler_name: str,
        sanitize_interval_seconds: int,
        clear_traces_simulation_seconds: int,
        log_level: str,
    ):
        self.group = group
        self.version = version
        self.node_properties_plural = node_properties_plural
        self.attribute_prefix = attribute_prefix
        self.property_prefix = property_prefix
        self.trace_prefix = trace_prefix
        self.contexts_annotation = contexts_annotation
        self.sanitizing_taint = sanitizing_taint
        self.scheduler_name = scheduler_name
        self.sanitize_interval_seconds = sanitize_interval_seconds
        self.clear_traces_simulation_seconds = clear_traces_simulation_seconds
        self.log_level = log_level

    @staticmethod
    def from_env() -> "Config":
        return Config(
            group=os.getenv("GROUP", GROUP_DEFAULT),
            version=os.getenv("VERSION", VERSION_DEFAULT),
            node_properties_plural=os.getenv(
                "NODE_PROPERTIES_PLURAL",
                NODE_PROPERTIES_PLURAL_DEFAULT,
            ),
            attribute_prefix=os.getenv("ATTRIBUTE_PREFIX", ATTRIBUTE_PREFIX_DEFAULT),
            property_prefix=os.getenv("PROPERTY_PREFIX", PROPERTY_PREFIX_DEFAULT),
            trace_prefix=os.getenv("TRACE_PREFIX", TRACE_PREFIX_DEFAULT),
            contexts_annotation=os.getenv(
                "CONTEXTS_ANNOTATION",
                CONTEXTS_ANNOTATION_DEFAULT,
            ),
            sanitizing_taint=os.getenv("SANITIZING_TAINT", SANITIZING_TAINT_DEFAULT),
            scheduler_name=os.getenv("SCHEDULER_NAME", SCHEDULER_NAME_DEFAULT),
            sanitize_interval_seconds=int(
                os.getenv(
                    "SANITIZE_INTERVAL_SECONDS",
                    SANITIZE_INTERVAL_SECONDS_DEFAULT,
                )
            ),
            clear_traces_simulation_seconds=int(
                os.getenv(
                    "CLEAR_TRACES_SIMULATION_SECONDS",
                    CLEAR_TRACES_SIMULATION_SECONDS_DEFAULT,
                )
            ),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )
