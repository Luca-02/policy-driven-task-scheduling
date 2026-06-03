import tempfile
import unittest
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from main import create_app
from src.config import Config
from src.dependencies import get_repository

D1 = {
    "name": "d1",
    "requirements": {"security": 2, "computation": 1},
    "size_mb": 1024,
    "nodes": ["kind-worker2"],
}

UPDATE_D1 = {
    "requirements": {"security": 3},
    "size_mb": 1,
    "nodes": [],
}


def make_cfg() -> Config:
    return Config(
        db_url="sqlite://",  # in-memory
        host="0.0.0.0",
        port=8443,
        tls_cert_file=None,
        tls_key_file=None,
        gatekeeper_api_version="externaldata.gatekeeper.sh/v1beta1",
        log_level="WARNING",
    )


class TestHealth(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app(make_cfg()))

    def test_healthz(self):
        r = self.client.get("/healthz")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"status": "ok"})


class TestCrudAndValidate(unittest.TestCase):

    def setUp(self):
        self.app = create_app(make_cfg())
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def _create_d1(self):
        return self.client.post(
            "/datasets",
            json=D1,
        )

    def test_create_get_list(self):
        self.assertEqual(self._create_d1().status_code, 201)
        r = self.client.get("/datasets/d1")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), D1)

    def test_duplicate_409(self):
        self._create_d1()
        self.assertEqual(self._create_d1().status_code, 409)

    def test_get_missing_404(self):
        self.assertEqual(self.client.get("/datasets/nope").status_code, 404)

    def test_update_replaces(self):
        self._create_d1()
        r = self.client.put("/datasets/d1", json=UPDATE_D1)
        self.assertEqual(r.status_code, 200)
        for k, v in UPDATE_D1.items():
            self.assertEqual(r.json()[k], v)

    def test_update_missing_404(self):
        r = self.client.put("/datasets/nope", json=UPDATE_D1)
        self.assertEqual(r.status_code, 404)

    def test_delete(self):
        self._create_d1()
        self.assertEqual(self.client.delete("/datasets/d1").status_code, 204)
        self.assertEqual(self.client.get("/datasets/d1").status_code, 404)

    def test_delete_missing_404(self):
        self.assertEqual(self.client.delete("/datasets/nope").status_code, 404)

    def test_validate_existing_and_missing(self):
        self._create_d1()
        r = self.client.post(
            "/validate",
            json={
                "apiVersion": "externaldata.gatekeeper.sh/v1beta1",
                "kind": "ProviderRequest",
                "request": {"keys": ["d1", "dx"]},
            },
        )
        self.assertEqual(r.status_code, 200)
        items = {it["key"]: it for it in r.json()["response"]["items"]}
        self.assertEqual(items["d1"]["error"], "")
        d1_value = items["d1"]["value"]
        for value in d1_value.values():
            self.assertIn(value, D1.values())
        self.assertIn("not found", items["dx"]["error"])

    def test_validate_empty_keys(self):
        r = self.client.post("/validate", json={"request": {"keys": []}})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["response"]["items"], [])
