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
    Act as a client for the dataset service.

    Fetches dataset metadata and encapsulates dataset-related logic such as the 
    computation of the effective property class beta*(t).

    TLS verification uses the provided CA certificate. If no CA is given, the 
    default system trust store is used.
    """

    def __init__(self, base_url: str, ca_cert_file: str | None = None):
        self._base_url = base_url.rstrip("/")
        if ca_cert_file:
            self._ssl_ctx = ssl.create_default_context(cafile=ca_cert_file)
        else:
            self._ssl_ctx = ssl.create_default_context()

    def _get_dataset(self, name: str) -> dict:
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

    def compute_effective_beta(self, beta_t: dict, datasets: list[str]) -> dict:
        """
        Compute the effective property class beta*(t) for a given set of datasets and task beta values.

        This is defined as beta*(t) = LUB(beta(t), beta(d1), beta(d2), ...), where beta(t) is the
        base task beta and beta(d) are fetched from the dataset service.

        Args:
            beta_t: A dictionary of task beta values.
            datasets: A list of dataset names.

        Returns:
            The computed effective beta as a dictionary.

        Raises:
            DatasetNotFoundError: If any dataset is not found (HTTP 404).
            DatasetServiceError: If there is any other error communicating with the dataset service.
        """
        beta_star_t: dict[str, int] = dict(beta_t)
        for dataset_name in datasets:
            dataset = self._get_dataset(dataset_name)

            for prop, level in (dataset.get("requirements") or {}).items():
                beta_star_t[prop] = max(beta_star_t.get(prop, 0), int(level))

        return beta_star_t
