import json
import ssl
import urllib.error
import urllib.parse
import urllib.request


class DatasetNotFoundError(Exception):
    """Raised when the dataset service returns 404 for a dataset name."""

    def __init__(self, dataset_name: str):
        super().__init__(f"Dataset not found: {dataset_name!r}")


class DatasetServiceError(Exception):
    """Raised on generic error communicating with the external dataset service."""


class DatasetService:
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

    def get_dataset(self, name: str) -> dict:
        """
        Fetch dataset metadata by name.

        Args:
            name: The dataset name to fetch.

        Returns:
            A dictionary containing the dataset metadata.

        Raises:
            DatasetNotFoundError: If the dataset is not found (HTTP 404).
            DatasetServiceError: If there is any other error.
        """
        url = f"{self._base_url}/datasets/{urllib.parse.quote(name, safe='')}"
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, context=self._ssl_ctx) as response:
                raw = response.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise DatasetNotFoundError(name)
            raise DatasetServiceError(
                f"Dataset service returned HTTP {e.code} for dataset {name!r}"
            )
        except urllib.error.URLError as e:
            raise DatasetServiceError(f"Dataset service unreachable: {e.reason}")
        except OSError as e:
            raise DatasetServiceError(f"Network error fetching dataset {name!r}: {e}")

        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as e:
            raise DatasetServiceError(
                f"Dataset service returned malformed JSON for dataset {name!r}: {e}"
            )

    def get_all_datasets(self, names: list[str]) -> list[dict]:
        """
        Fetch metadata for a list of datasets.

        Args:
            names: A list of dataset names to fetch.

        Returns:
            A list of dictionaries containing the dataset metadata.

        Raises:
            DatasetNotFoundError: If any dataset is not found (HTTP 404).
            DatasetServiceError: If there is any other error.
        """
        return [self.get_dataset(name) for name in names]
