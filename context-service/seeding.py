import json
import urllib.error
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
logger = logging.getLogger("context-service-seed")


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


def _post(url: str, payload, ctx: ssl.SSLContext) -> str:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, context=ctx) as response:
        text = response.read().decode()
        try:
            return json.dumps(json.loads(text), indent=2)
        except Exception:
            return text


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

    # Conflicts are seeded first: the model requires X_conf to be
    # well-formed with respect to auth(i) at all times, and this mirrors
    # the assumption (documented in the thesis) that the conflict
    # configuration precedes issuer/dataset onboarding in the prototype.
    conflicts = data.get("conflicts", [])
    logger.info(f"Seeding {len(conflicts)} context conflicts to {cfg.service_url}...")
    for pair in conflicts:
        try:
            result = _post(f"{cfg.service_url}/conflicts", pair, ctx)
            logger.info(f"Conflict seeded: {result}")
        except urllib.error.HTTPError as e:
            logger.error(
                f"Conflict seeding error for {pair}: HTTP {e.code} - {e.read().decode()}"
            )

    issuers = data.get("issuers", [])
    logger.info(f"Seeding {len(issuers)} issuers to {cfg.service_url}...")
    try:
        result = _post(f"{cfg.service_url}/issuers/batch", issuers, ctx)
        logger.info(f"Issuers seeded: {result}")
    except urllib.error.HTTPError as e:
        logger.error(f"Issuer seeding error: HTTP {e.code} - {e.read().decode()}")
    except Exception as e:
        logger.error(f"Connection error: {e}")
        sys.exit(1)

    logger.info("Completed! All conflicts and issuers processed successfully.")


if __name__ == "__main__":
    main()
