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
    """Raised on any non-404 error communicating with the dataset service."""


class DatasetClient:
    """
    Thin HTTP client for the dataset service.

    Fetches dataset metadata (beta(d) and placement lambda(d)) needed to compute
    the effective property class beta*(t) in the TaskRequest controller.

    TLS verification uses the provided CA certificate. If no CA is given,
    the default system trust store is used (suitable for tests with plain HTTP).
    """

    def __init__(self, base_url: str, ca_cert_file: str | None = None):
        self._base_url = base_url.rstrip("/")
        if ca_cert_file:
            self._ssl_ctx = ssl.create_default_context(cafile=ca_cert_file)
        else:
            self._ssl_ctx = ssl.create_default_context()

    def get_dataset(self, name: str) -> dict:
        """
        Fetch dataset metadata by name.

        Args:
            name: The dataset name to fetch.

        Returns:
            A dictionary containing the dataset metadata.

        Raises:
            DatasetNotFoundError: If the dataset is not found (HTTP 404).
            DatasetServiceError: If there is any other error communicating with the dataset service.
        """
        url = f"{self._base_url}/datasets/{urllib.parse.quote(name, safe='')}"
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, context=self._ssl_ctx) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise DatasetNotFoundError(name)
            raise DatasetServiceError(
                f"Dataset service returned HTTP {e.code} for dataset {name!r}"
            )
        except urllib.error.URLError as e:
            raise DatasetServiceError(f"Dataset service unreachable: {e.reason}")
