import os

GROUP_DEFAULT = "policydriven.unimi.it"
VERSION_DEFAULT = "v1alpha1"
TASK_REQUESTS_PLURAL_DEFAULT = "taskrequests"
TASK_NAMESPACE_DEFAULT = "compute"
DATASET_SERVICE_URL_DEFAULT = "https://127.0.0.1:8443"
TASK_REQUEST_KIND_DEFAULT = "TaskRequest"
# Label prefix used to link a Job back to its originating TaskRequest.
JOB_LABEL_PREFIX_DEFAULT = f"scheduling.task.{GROUP_DEFAULT}"
# Annotation prefix for carrying the serialised beta*(t) for the scheduler extender.
JOB_ANNOTATION_PREFIX_DEFAULT = f"scheduling.task.{GROUP_DEFAULT}"
TASK_REQUEST_REF_LABEL_DEFAULT = "task-request"
BETA_STAR_ANNOTATION_DEFAULT = "beta-star"
DATASETS_ANNOTATION_DEFAULT = "datasets"


class Config:
    """Controller configuration loaded from environment variables."""

    def __init__(
        self,
        group: str,
        version: str,
        task_requests_plural: str,
        task_namespace: str,
        dataset_service_url: str,
        ca_cert_file: str | None,
        task_request_kind: str,
        job_label_prefix: str,
        job_annotation_prefix: str,
        task_request_ref_label: str,
        beta_star_annotation: str,
        datasets_annotation: str,
        log_level: str,
    ):
        self.group = group
        self.version = version
        self.task_requests_plural = task_requests_plural
        self.task_namespace = task_namespace
        self.dataset_service_url = dataset_service_url
        self.ca_cert_file = ca_cert_file
        self.job_label_prefix = job_label_prefix
        self.task_request_kind = task_request_kind
        self.job_annotation_prefix = job_annotation_prefix
        self.task_request_ref_label = task_request_ref_label
        self.beta_star_annotation = beta_star_annotation
        self.datasets_annotation = datasets_annotation
        self.log_level = log_level

    @staticmethod
    def from_env() -> "Config":
        return Config(
            group=os.getenv("GROUP", GROUP_DEFAULT),
            version=os.getenv("VERSION", VERSION_DEFAULT),
            task_requests_plural=os.getenv(
                "TASK_REQUESTS_PLURAL", TASK_REQUESTS_PLURAL_DEFAULT
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
            beta_star_annotation=os.getenv(
                "BETA_STAR_ANNOTATION", BETA_STAR_ANNOTATION_DEFAULT
            ),
            datasets_annotation=os.getenv(
                "DATASETS_ANNOTATION", DATASETS_ANNOTATION_DEFAULT
            ),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )
