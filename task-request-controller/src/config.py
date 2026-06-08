import os

GROUP_DEFAULT = "policydriven.unimi.it"
VERSION_DEFAULT = "v1alpha1"
PLURAL_DEFAULT = "taskrequests"
TASK_NAMESPACE_DEFAULT = "compute"
DATASET_SERVICE_URL_DEFAULT = "https://127.0.0.1:8443"
# Label prefix used to link a Job back to its originating TaskRequest.
TASK_REQUEST_REF_LABEL_PREFIX_DEFAULT = f"scheduling.task.{GROUP_DEFAULT}"
# Annotation prefix for carrying the serialised beta*(t) for the scheduler extender.
BETA_STAR_ANNOTATION_PREFIX_DEFAULT = f"scheduling.task.{GROUP_DEFAULT}"


class Config:
    """Controller configuration loaded from environment variables."""

    def __init__(
        self,
        group: str,
        version: str,
        plural: str,
        task_namespace: str,
        dataset_service_url: str,
        ca_cert_file: str | None,
        task_request_ref_label_prefix: str,
        beta_star_annotation_prefix: str,
        log_level: str,
    ):
        self.group = group
        self.version = version
        self.plural = plural
        self.task_namespace = task_namespace
        self.dataset_service_url = dataset_service_url
        self.ca_cert_file = ca_cert_file
        self.task_request_ref_label_prefix = task_request_ref_label_prefix
        self.beta_star_annotation_prefix = beta_star_annotation_prefix
        self.log_level = log_level

    @staticmethod
    def from_env() -> "Config":
        return Config(
            group=os.getenv("GROUP", GROUP_DEFAULT),
            version=os.getenv("VERSION", VERSION_DEFAULT),
            plural=os.getenv("PLURAL", PLURAL_DEFAULT),
            task_namespace=os.getenv("TASK_NAMESPACE", TASK_NAMESPACE_DEFAULT),
            dataset_service_url=os.getenv(
                "DATASET_SERVICE_URL", DATASET_SERVICE_URL_DEFAULT
            ),
            ca_cert_file=os.getenv("CA_CERT_FILE"),
            task_request_ref_label_prefix=os.getenv(
                "TASK_REQUEST_REF_LABEL_PREFIX",
                TASK_REQUEST_REF_LABEL_PREFIX_DEFAULT,
            ),
            beta_star_annotation_prefix=os.getenv(
                "BETA_STAR_ANNOTATION_PREFIX", BETA_STAR_ANNOTATION_PREFIX_DEFAULT
            ),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )
