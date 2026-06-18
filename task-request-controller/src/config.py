import os

GROUP_DEFAULT = "policydriven.unimi.it"
VERSION_DEFAULT = "v1alpha1"
TASK_REQUESTS_PLURAL_DEFAULT = "taskrequests"
GEOGRAPHICAL_GROUPS_PLURAL_DEFAULT = "geographicalgroups"
TASK_NAMESPACE_DEFAULT = "compute"
TASK_REQUEST_KIND_DEFAULT = "TaskRequest"
JOB_LABEL_PREFIX_DEFAULT = f"scheduling.task.{GROUP_DEFAULT}"
JOB_ANNOTATION_PREFIX_DEFAULT = f"scheduling.task.{GROUP_DEFAULT}"
TASK_REQUEST_REF_LABEL_DEFAULT = "task-request"
DATASETS_ANNOTATION_DEFAULT = "datasets"
BETA_STAR_ANNOTATION_DEFAULT = "beta-star"
GEO_STAR_ANNOTATION_DEFAULT = "geo-star"
NODE_PROPERTY_PREFIX_DEFAULT = f"property.node.{GROUP_DEFAULT}"
NODE_TOPOLOGY_LOCATION_LABEL_DEFAULT = f"topology.node.{GROUP_DEFAULT}/location"
DATASET_SERVICE_URL_DEFAULT = "https://127.0.0.1:8443"


class Config:
    """Controller configuration loaded from environment variables."""

    def __init__(
        self,
        group: str,
        version: str,
        task_requests_plural: str,
        geographical_groups_plural: str,
        task_namespace: str,
        task_request_kind: str,
        job_label_prefix: str,
        job_annotation_prefix: str,
        task_request_ref_label: str,
        datasets_annotation: str,
        beta_star_annotation: str,
        geo_star_annotation: str,
        node_property_prefix: str,
        node_topology_location_label: str,
        dataset_service_url: str,
        ca_cert_file: str | None,
        log_level: str,
    ):
        self.group = group
        self.version = version
        self.task_requests_plural = task_requests_plural
        self.geographical_groups_plural = geographical_groups_plural
        self.task_namespace = task_namespace
        self.dataset_service_url = dataset_service_url
        self.ca_cert_file = ca_cert_file
        self.job_label_prefix = job_label_prefix
        self.task_request_kind = task_request_kind
        self.job_annotation_prefix = job_annotation_prefix
        self.task_request_ref_label = task_request_ref_label
        self.datasets_annotation = datasets_annotation
        self.beta_star_annotation = beta_star_annotation
        self.geo_star_annotation = geo_star_annotation
        self.node_property_prefix = node_property_prefix
        self.node_topology_location_label = node_topology_location_label
        self.log_level = log_level

    @staticmethod
    def from_env() -> "Config":
        return Config(
            group=os.getenv("GROUP", GROUP_DEFAULT),
            version=os.getenv("VERSION", VERSION_DEFAULT),
            task_requests_plural=os.getenv(
                "TASK_REQUESTS_PLURAL", TASK_REQUESTS_PLURAL_DEFAULT
            ),
            geographical_groups_plural=os.getenv(
                "GEOGRAPHICAL_GROUPS_PLURAL", GEOGRAPHICAL_GROUPS_PLURAL_DEFAULT
            ),
            task_namespace=os.getenv("TASK_NAMESPACE", TASK_NAMESPACE_DEFAULT),
            dataset_service_url=os.getenv(
                "DATASET_SERVICE_URL", DATASET_SERVICE_URL_DEFAULT
            ),
            ca_cert_file=os.getenv("CA_CERT_FILE"),
            task_request_kind=os.getenv("TASK_REQUEST_KIND", TASK_REQUEST_KIND_DEFAULT),
            job_label_prefix=os.getenv(
                "JOB_LABEL_PREFIX",
                JOB_LABEL_PREFIX_DEFAULT,
            ),
            job_annotation_prefix=os.getenv(
                "JOB_ANNOTATION_PREFIX", JOB_ANNOTATION_PREFIX_DEFAULT
            ),
            task_request_ref_label=os.getenv(
                "TASK_REQUEST_REF_LABEL", TASK_REQUEST_REF_LABEL_DEFAULT
            ),
            datasets_annotation=os.getenv(
                "DATASETS_ANNOTATION", DATASETS_ANNOTATION_DEFAULT
            ),
            beta_star_annotation=os.getenv(
                "BETA_STAR_ANNOTATION", BETA_STAR_ANNOTATION_DEFAULT
            ),
            geo_star_annotation=os.getenv(
                "GEO_STAR_ANNOTATION", GEO_STAR_ANNOTATION_DEFAULT
            ),
            node_property_prefix=os.getenv(
                "NODE_PROPERTY_PREFIX", NODE_PROPERTY_PREFIX_DEFAULT
            ),
            node_topology_location_label=os.getenv(
                "NODE_TOPOLOGY_LOCATION_LABEL", NODE_TOPOLOGY_LOCATION_LABEL_DEFAULT
            ),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )
