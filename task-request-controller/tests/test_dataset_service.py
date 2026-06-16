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


class TestGetDataset(unittest.TestCase):
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
            result = self.svc._get_dataset("d1")
        self.assertEqual(result, payload)

    def test_not_found_raises_dataset_not_found_error(self):
        from urllib.error import HTTPError

        with patch(
            "urllib.request.urlopen",
            side_effect=HTTPError(None, 404, "Not Found", {}, None),
        ):
            with self.assertRaises(DatasetNotFoundError) as ctx:
                self.svc._get_dataset("missing")
        self.assertIn("missing", str(ctx.exception))

    def test_http_500_raises_dataset_service_error(self):
        from urllib.error import HTTPError

        with patch(
            "urllib.request.urlopen",
            side_effect=HTTPError(None, 500, "Internal Server Error", {}, None),
        ):
            with self.assertRaises(DatasetServiceError):
                self.svc._get_dataset("d1")

    def test_http_503_raises_dataset_service_error(self):
        from urllib.error import HTTPError

        with patch(
            "urllib.request.urlopen",
            side_effect=HTTPError(None, 503, "Service Unavailable", {}, None),
        ):
            with self.assertRaises(DatasetServiceError):
                self.svc._get_dataset("d1")

    def test_url_error_raises_dataset_service_error(self):
        from urllib.error import URLError

        with patch(
            "urllib.request.urlopen",
            side_effect=URLError("connection refused"),
        ):
            with self.assertRaises(DatasetServiceError):
                self.svc._get_dataset("d1")

    def test_os_error_raises_dataset_service_error(self):
        with patch("urllib.request.urlopen", side_effect=OSError("timeout")):
            with self.assertRaises(DatasetServiceError):
                self.svc._get_dataset("d1")

    def test_malformed_json_raises_dataset_service_error(self):
        resp = MagicMock()
        resp.read.return_value = b"not-valid-json{"
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=resp):
            with self.assertRaises(DatasetServiceError):
                self.svc._get_dataset("d1")

    def test_empty_json_object_is_valid(self):
        with patch("urllib.request.urlopen", return_value=mock_response({})):
            result = self.svc._get_dataset("d1")
        self.assertEqual(result, {})


class TestComputeBetaStar(unittest.TestCase):
    def setUp(self):
        self.svc = make_service()
        self.svc._get_dataset = MagicMock()

    def test_no_datasets_returns_task_requirements(self):
        result = self.svc.compute_effective_beta({"security": 2, "computation": 1}, [])
        self.assertEqual(result, {"security": 2, "computation": 1})
        self.svc._get_dataset.assert_not_called()

    def test_empty_requirements_and_no_datasets(self):
        result = self.svc.compute_effective_beta({}, [])
        self.assertEqual(result, {})

    def test_dataset_raises_existing_property(self):
        self.svc._get_dataset.return_value = {"requirements": {"security": 2}}
        result = self.svc.compute_effective_beta({"security": 1}, ["d1"])
        self.assertEqual(result["security"], 2)

    def test_task_requirement_prevails_over_dataset(self):
        self.svc._get_dataset.return_value = {"requirements": {"security": 1}}
        result = self.svc.compute_effective_beta({"security": 3}, ["d1"])
        self.assertEqual(result["security"], 3)

    def test_dataset_introduces_new_property(self):
        self.svc._get_dataset.return_value = {"requirements": {"computation": 3}}
        result = self.svc.compute_effective_beta({"security": 1}, ["d1"])
        self.assertEqual(result, {"security": 1, "computation": 3})

    def test_multiple_datasets_lub(self):
        self.svc._get_dataset.side_effect = [
            {"requirements": {"security": 2, "computation": 1}},
            {"requirements": {"security": 1, "computation": 3}},
        ]
        result = self.svc.compute_effective_beta(
            {"security": 1, "computation": 2}, ["d1", "d2"]
        )
        self.assertEqual(result, {"security": 2, "computation": 3})

    def test_datasets_fetched_in_order(self):
        self.svc._get_dataset.return_value = {"requirements": {}}
        self.svc.compute_effective_beta({}, ["d1", "d2", "d3"])
        calls = [c[0][0] for c in self.svc._get_dataset.call_args_list]
        self.assertEqual(calls, ["d1", "d2", "d3"])

    def test_dataset_with_null_requirements(self):
        self.svc._get_dataset.return_value = {"requirements": None}
        result = self.svc.compute_effective_beta({"security": 2}, ["d1"])
        self.assertEqual(result, {"security": 2})

    def test_dataset_with_missing_requirements_key(self):
        self.svc._get_dataset.return_value = {"size_mb": 1024}
        result = self.svc.compute_effective_beta({"security": 2}, ["d1"])
        self.assertEqual(result, {"security": 2})

    def test_level_zero_in_dataset_does_not_lower_task_requirement(self):
        self.svc._get_dataset.return_value = {"requirements": {"security": 0}}
        result = self.svc.compute_effective_beta({"security": 2}, ["d1"])
        self.assertEqual(result["security"], 2)

    def test_propagates_dataset_not_found(self):
        self.svc._get_dataset.side_effect = DatasetNotFoundError("not found")
        with self.assertRaises(DatasetNotFoundError):
            self.svc.compute_effective_beta({}, ["missing"])

    def test_propagates_dataset_service_error(self):
        self.svc._get_dataset.side_effect = DatasetServiceError("unreachable")
        with self.assertRaises(DatasetServiceError):
            self.svc.compute_effective_beta({}, ["d1"])

    def test_stops_at_first_missing_dataset(self):
        self.svc._get_dataset.side_effect = DatasetNotFoundError("not found")
        with self.assertRaises(DatasetNotFoundError):
            self.svc.compute_effective_beta({}, ["missing", "d2"])
        self.svc._get_dataset.assert_called_once_with("missing")
