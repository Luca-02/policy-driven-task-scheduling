import os

DB_URL_DEFAULT = "sqlite://"
HOST_DEFAULT = "127.0.0.1"
PORT_DEFAULT = 8443


class Config:
    """Service configuration loaded from environment variables."""

    def __init__(
        self,
        db_url: str,
        host: str,
        port: int,
        tls_cert_file: str | None,
        tls_key_file: str | None,
        log_level: str,
    ):
        self.db_url = db_url
        self.host = host
        self.port = port
        self.tls_cert_file = tls_cert_file
        self.tls_key_file = tls_key_file
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
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )
