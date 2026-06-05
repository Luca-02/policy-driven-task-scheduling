import json
import urllib.request
import ssl
import sys
import os
import logging

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="[%(asctime)s] %(name)-s [%(levelname)-s] %(message)s",
)
logger = logging.getLogger("dataset-service-seed")


class Config:
    """Service configuration, loaded from environment variables."""

    def __init__(self, seed_data_file: str, service_url: str, ca_cert_file: str = None):
        self.seed_data_file = seed_data_file
        self.service_url = service_url
        self.ca_cert_file = ca_cert_file

    @staticmethod
    def from_env() -> "Config":
        return Config(
            seed_data_file=os.getenv("SEED_DATA_FILE"),
            service_url=os.getenv("SERVICE_URL"),
            ca_cert_file=os.getenv("CA_CERT_FILE"),
        )


def main():
    cfg = Config.from_env()

    if not cfg.seed_data_file or not cfg.service_url:
        logger.error("Missing SEED_DATA_FILE or SERVICE_URL environment variables.")
        sys.exit(1)

    try:
        with open(cfg.seed_data_file, "r") as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.error(f"Seed file not found at {cfg.seed_data_file}")
        sys.exit(1)

    if cfg.ca_cert_file:
        logger.info(
            f"Using CA certificate from {cfg.ca_cert_file} for secure connection."
        )
        ctx = ssl.create_default_context(cafile=cfg.ca_cert_file)
    else:
        logger.warning("No CA certificate provided, skipping SSL verification.")
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    datasets = data.get("datasets", [])
    logger.info(f"Starting seeding of {len(datasets)} datasets to {cfg.service_url}...")
    payload = json.dumps(datasets).encode("utf-8")
    req = urllib.request.Request(
        f"{cfg.service_url}/datasets/batch",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, context=ctx) as response:
            response_text = response.read().decode()
            try:
                parsed = json.loads(response_text)
                formatted = json.dumps(parsed, indent=2)
            except Exception:
                formatted = response_text
            logger.info(f"Seeding completed: {formatted}")
    except urllib.error.HTTPError as e:
        logger.error(f"Seeding error: HTTP {e.code} - {e.read().decode()}")
    except Exception as e:
        logger.error(f"Connection error: {e}")
        sys.exit(1)

    logger.info(f"Completed! All datasets processed successfully.")


if __name__ == "__main__":
    main()
