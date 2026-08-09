import json
import ssl
import urllib.error
import urllib.request


class DatasetNotFoundException(Exception):
    """Raised when a dataset is not found in the external dataset service."""


class DatasetClientException(Exception):
    """Raised on any error communicating with the external dataset service."""


class DatasetClient:
    """
    Act as a HTTP client for the dataset service.

    TLS verification uses the provided CA certificate.
    If no CA is given, TLS verification is disabled.
    """

    def __init__(self, base_url: str, ca_cert_file: str | None = None):
        self._base_url = base_url.rstrip("/")
        if ca_cert_file:
            self._ssl_ctx = ssl.create_default_context(cafile=ca_cert_file)
        else:
            self._ssl_ctx = ssl.create_default_context()
            self._ssl_ctx.check_hostname = False
            self._ssl_ctx.verify_mode = ssl.CERT_NONE

    def get_all_datasets(self, names: list[str]) -> list[dict]:
        """
        Fetch metadata for a list of datasets in a single request.

        Uses the dataset service's /datasets/query endpoint, which filters
        by name server-side and returns only the requested datasets in one
        round trip, instead of issuing one HTTP request per dataset name.

        Args:
            names: A list of dataset names to fetch.

        Returns:
            A list of dictionaries containing the dataset metadata.

        Raises:
            DatasetNotFoundException: If any of the requested datasets is not
                found.
            DatasetClientException: If there is any other error communicating 
                with the dataset service.
        """
        if not names:
            return []

        url = f"{self._base_url}/datasets/query"
        body = json.dumps({"keys": names}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, context=self._ssl_ctx) as response:
                raw = response.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise DatasetNotFoundException(
                    self._extract_detail(e, f"Dataset(s) not found: {names!r}")
                )
            raise DatasetClientException(
                f"Dataset service returned HTTP {e.code} for dataset query {names!r}"
            )
        except urllib.error.URLError as e:
            raise DatasetClientException(f"Dataset service unreachable: {e.reason}")
        except OSError as e:
            raise DatasetClientException(
                f"Network error querying datasets {names!r}: {e}"
            )

        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as e:
            raise DatasetClientException(
                f"Dataset service returned malformed JSON for dataset query {names!r}: {e}"
            )

    @staticmethod
    def _extract_detail(e: urllib.error.HTTPError, fallback: str) -> str:
        """
        Return the detail message from a JSON error body, as returned
        verbatim by the dataset service (e.g. "Datasets not found: d1, d2").

        Falls back to the given message if the error body cannot be parsed.
        """
        try:
            detail = json.loads(e.read().decode("utf-8")).get("detail")
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError, OSError):
            return fallback

        return detail if isinstance(detail, str) and detail else fallback
