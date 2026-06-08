import os

DB_URL_DEFAULT = "sqlite://"
HOST_DEFAULT = "127.0.0.1"
PORT_DEFAULT = 8443
GATEKEEPER_API_VERSION_DEFAULT = "externaldata.gatekeeper.sh/v1beta1"


class Config:
    """Service configuration loaded from environment variables."""

    def __init__(
        self,
        db_url: str,
        host: str,
        port: int,
        tls_cert_file: str | None,
        tls_key_file: str | None,
        gatekeeper_api_version: str,
        log_level: str,
    ):
        self.db_url = db_url
        self.host = host
        self.port = port
        self.tls_cert_file = tls_cert_file
        self.tls_key_file = tls_key_file
        self.gatekeeper_api_version = gatekeeper_api_version
        self.log_level = log_level

    @property
    def tls_enabled(self) -> bool:
        return bool(self.tls_cert_file and self.tls_key_file)

    @staticmethod
    def from_env() -> "Config":
        return Config(
            db_url=os.getenv("DB_URL", DB_URL_DEFAULT),
            host=os.getenv("HOST", HOST_DEFAULT),
            port=int(os.getenv("PORT", PORT_DEFAULT)),
            tls_cert_file=os.getenv("TLS_CERT_FILE"),
            tls_key_file=os.getenv("TLS_KEY_FILE"),
            gatekeeper_api_version=os.getenv(
                "GATEKEEPER_API_VERSION", GATEKEEPER_API_VERSION_DEFAULT
            ),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )
