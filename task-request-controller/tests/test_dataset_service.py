import json
import unittest
from unittest.mock import MagicMock, patch

from src.dataset_service import (
    DatasetService,
    DatasetNotFoundError,
    DatasetServiceError,
)


def make_service() -> DatasetService:
    return DatasetService(base_url="http://dataset-service", ca_cert_file=None)


def mock_response(data: dict) -> MagicMock:
    resp = MagicMock()
    resp.read.return_value = json.dumps(data).encode()
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


class TestDatasetService(unittest.TestCase):
    def setUp(self):
        self.svc = make_service()

    def test_success_returns_dict(self):
        payload = {
            "name": "d1",
            "requirements": {"security": 2, "computation": 1},
            "size_mb": 1024,
            "nodes": ["kind-worker1"],
        }
        with patch("urllib.request.urlopen", return_value=mock_response(payload)):
            result = self.svc.get_dataset("d1")
        self.assertEqual(result, payload)

    def test_not_found_raises_dataset_not_found_error(self):
        from urllib.error import HTTPError

        with patch(
            "urllib.request.urlopen",
            side_effect=HTTPError(None, 404, "Not Found", {}, None),
        ):
            with self.assertRaises(DatasetNotFoundError) as ctx:
                self.svc.get_dataset("missing")
        self.assertIn("missing", str(ctx.exception))

    def test_http_500_raises_dataset_service_error(self):
        from urllib.error import HTTPError

        with patch(
            "urllib.request.urlopen",
            side_effect=HTTPError(None, 500, "Internal Server Error", {}, None),
        ):
            with self.assertRaises(DatasetServiceError):
                self.svc.get_dataset("d1")

    def test_http_503_raises_dataset_service_error(self):
        from urllib.error import HTTPError

        with patch(
            "urllib.request.urlopen",
            side_effect=HTTPError(None, 503, "Service Unavailable", {}, None),
        ):
            with self.assertRaises(DatasetServiceError):
                self.svc.get_dataset("d1")

    def test_url_error_raises_dataset_service_error(self):
        from urllib.error import URLError

        with patch(
            "urllib.request.urlopen",
            side_effect=URLError("connection refused"),
        ):
            with self.assertRaises(DatasetServiceError):
                self.svc.get_dataset("d1")

    def test_os_error_raises_dataset_service_error(self):
        with patch("urllib.request.urlopen", side_effect=OSError("timeout")):
            with self.assertRaises(DatasetServiceError):
                self.svc.get_dataset("d1")

    def test_malformed_json_raises_dataset_service_error(self):
        resp = MagicMock()
        resp.read.return_value = b"not-valid-json{"
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=resp):
            with self.assertRaises(DatasetServiceError):
                self.svc.get_dataset("d1")

    def test_empty_json_object_is_valid(self):
        with patch("urllib.request.urlopen", return_value=mock_response({})):
            result = self.svc.get_dataset("d1")
        self.assertEqual(result, {})

    def test_get_all_datasets_success(self):
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
            side_effect=[
                mock_response(payload1),
                mock_response(payload2),
            ],
        ):
            result = self.svc.get_all_datasets(["d1", "d2"])
        self.assertEqual(result, [payload1, payload2])
