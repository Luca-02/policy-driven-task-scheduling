import io
import json
import unittest
from unittest.mock import MagicMock, patch

from urllib.error import HTTPError

from src.dataset_client import (
    DatasetClient,
    DatasetNotFoundException,
    DatasetClientException,
)


def make_client() -> DatasetClient:
    return DatasetClient(base_url="http://dataset-service", ca_cert_file=None)


def mock_response(data) -> MagicMock:
    resp = MagicMock()
    resp.read.return_value = json.dumps(data).encode()
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def http_error_with_body(code: int, msg: str, detail: dict) -> HTTPError:
    fp = io.BytesIO(json.dumps(detail).encode())
    return HTTPError(None, code, msg, {}, fp)


class TestDatasetClientGetAllDatasets(unittest.TestCase):
    def setUp(self):
        self.client = make_client()

    def test_empty_names_short_circuits_without_request(self):
        with patch("urllib.request.urlopen") as mocked_urlopen:
            result = self.client.get_all_datasets([])
        self.assertEqual(result, [])
        mocked_urlopen.assert_not_called()

    def test_success_uses_single_query_request(self):
        payload1 = {
            "name": "d1",
            "requirements": {"security": 2, "computation": 1},
            "size_mb": 1024,
            "nodes": ["kind-worker1"],
        }
        payload2 = {
            "name": "d2",
            "requirements": {"security": 1, "computation": 2},
            "size_mb": 2048,
            "nodes": ["kind-worker2"],
        }
        with patch(
            "urllib.request.urlopen",
            return_value=mock_response([payload1, payload2]),
        ) as mocked_urlopen:
            result = self.client.get_all_datasets(["d1", "d2"])

        self.assertEqual(result, [payload1, payload2])
        # A single HTTP round trip must be issued, regardless of dataset count.
        mocked_urlopen.assert_called_once()
        sent_request = mocked_urlopen.call_args[0][0]
        self.assertTrue(sent_request.full_url.endswith("/datasets/query"))
        self.assertEqual(
            json.loads(sent_request.data.decode("utf-8")), {"keys": ["d1", "d2"]}
        )

    def test_not_found_raises_dataset_not_found_with_detail_message(self):
        error = http_error_with_body(
            404, "Not Found", {"detail": "Datasets not found: d2, d3"}
        )
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(DatasetNotFoundException) as ctx:
                self.client.get_all_datasets(["d1", "d2", "d3"])
        self.assertEqual(str(ctx.exception), "Datasets not found: d2, d3")

    def test_not_found_falls_back_when_body_unparsable(self):
        from urllib.error import HTTPError

        error = HTTPError(None, 404, "Not Found", {}, None)
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(DatasetNotFoundException) as ctx:
                self.client.get_all_datasets(["d1", "d2"])
        self.assertIn("d1", str(ctx.exception))
        self.assertIn("d2", str(ctx.exception))

    def test_http_500_raises_dataset_client_exception(self):
        from urllib.error import HTTPError

        with patch(
            "urllib.request.urlopen",
            side_effect=HTTPError(None, 500, "Internal Server Error", {}, None),
        ):
            with self.assertRaises(DatasetClientException):
                self.client.get_all_datasets(["d1", "d2"])

    def test_url_error_raises_dataset_client_exception(self):
        from urllib.error import URLError

        with patch(
            "urllib.request.urlopen",
            side_effect=URLError("connection refused"),
        ):
            with self.assertRaises(DatasetClientException):
                self.client.get_all_datasets(["d1"])

    def test_os_error_raises_dataset_client_exception(self):
        with patch("urllib.request.urlopen", side_effect=OSError("timeout")):
            with self.assertRaises(DatasetClientException):
                self.client.get_all_datasets(["d1"])

    def test_malformed_json_raises_dataset_client_exception(self):
        resp = MagicMock()
        resp.read.return_value = b"not-valid-json{"
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=resp):
            with self.assertRaises(DatasetClientException):
                self.client.get_all_datasets(["d1"])
