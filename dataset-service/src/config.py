import os

DEFAULT_GATEKEEPER_API_VERSION = "externaldata.gatekeeper.sh/v1beta1"


class Config:
    """Service configuration, loaded from environment variables."""

    def __init__(
        self,
        database_path: str,
        seed_path: str,
        host: str,
        port: int,
        gatekeeper_api_version: str,
        log_level: str,
    ):
        self.database_path = database_path
        self.seed_path = seed_path
        self.host = host
        self.port = port
        self.gatekeeper_api_version = gatekeeper_api_version
        self.log_level = log_level

    @staticmethod
    def from_env() -> "Config":
        return Config(
            # TinyDB stores everything in this single, human-readable JSON file.
            # In the cluster it lives on a writable volume (emptyDir/PVC).
            database_path=os.getenv("DB_PATH", "/data/datasets.json"),
            seed_path=os.getenv("SEED_PATH", "/data/seed.json"),
            host=os.getenv("HOST", "0.0.0.0"),
            port=int(os.getenv("PORT", "8443")),
            gatekeeper_api_version=os.getenv(
                "GATEKEEPER_API_VERSION", DEFAULT_GATEKEEPER_API_VERSION
            ),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )
