import unittest

from fastapi.testclient import TestClient

from main import create_app
from src.config import Config

D1 = {
    "name": "d1",
    "requirements": {"security": 2, "computation": 1},
    "size_mb": 1024,
    "nodes": ["kind-worker2"],
    "geo": "eu",
    "static": False,
    "contexts": ["personal-data"],
}

D2 = {
    "name": "d2",
    "requirements": {"security": 1, "computation": 2},
    "size_mb": 2048,
    "nodes": ["kind-worker3"],
    "static": True,
    "contexts": [],
}

UPDATE_D1 = {
    "requirements": {"security": 3},
    "size_mb": 1,
    "nodes": [],
    "geo": "as",
    "static": True,
    "contexts": ["personal-data", "medical"],
}


def make_cfg() -> Config:
    return Config(
        db_url="sqlite://",  # in-memory
        host="0.0.0.0",
        port=8443,
        tls_cert_file=None,
        tls_key_file=None,
        log_level="WARNING",
        debug_mode=True,
    )


class TestBase(unittest.TestCase):
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

    def _create_multiple(self):
        return self.client.post(
            "/datasets/batch",
            json=[D1, D2],
        )


class TestHealth(TestBase):
    def test_healthz(self):
        r = self.client.get("/healthz")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"status": "ok"})


class TestDatasets(TestBase):
    def test_create_single(self):
        self.assertEqual(self._create_d1().status_code, 201)
        r = self.client.get("/datasets/d1")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), D1)

    def test_create_multiple(self):
        r = self._create_multiple()
        self.assertEqual(r.status_code, 201)
        self.assertEqual(len(r.json()), 2)
        for dataset in r.json():
            if dataset["name"] == "d1":
                self.assertEqual(dataset, D1)
            elif dataset["name"] == "d2":
                self.assertEqual(dataset, D2)
            else:
                self.fail(f"Unexpected dataset name: {dataset['name']}")

    def test_query_existing(self):
        self._create_multiple()
        r = self.client.post("/datasets/query", json={"keys": ["d1", "d2"]})
        self.assertEqual(r.status_code, 200)
        for dataset in r.json():
            if dataset["name"] == "d1":
                self.assertEqual(dataset, D1)
            elif dataset["name"] == "d2":
                self.assertEqual(dataset, D2)
            else:
                self.fail(f"Unexpected dataset name: {dataset['name']}")

    def test_create_without_contexts_defaults_to_public(self):
        public_dataset = {**D2, "name": "public"}
        del public_dataset["contexts"]
        self.client.post("/datasets", json=public_dataset)
        r = self.client.get("/datasets/public")
        self.assertEqual(r.json()["contexts"], [])

    def test_query_empty_keys_returns_empty_list(self):
        r = self.client.post("/datasets/query", json={"keys": []})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

    def test_query_missing_returns_404(self):
        self._create_d1()
        r = self.client.post("/datasets/query", json={"keys": ["d1", "nope"]})
        self.assertEqual(r.status_code, 404)

    def test_duplicate_409(self):
        self._create_d1()
        self.assertEqual(self._create_d1().status_code, 409)

    def test_multiple_duplicate_409(self):
        self._create_multiple()
        self.assertEqual(self._create_multiple().status_code, 409)

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

    def test_delete_all(self):
        self._create_multiple()
        r = self.client.delete("/datasets")
        self.assertEqual(r.status_code, 204)
        self.assertEqual(self.client.get("/datasets/d1").status_code, 404)
        self.assertEqual(self.client.get("/datasets/d2").status_code, 404)

    def test_delete_all_no_datasets(self):
        r = self.client.delete("/datasets")
        self.assertEqual(r.status_code, 404)


class TestProvider(TestBase):
    def test_validate_existing_and_missing(self):
        self._create_multiple()
        r = self.client.post(
            "/validate",
            json={
                "apiVersion": "externaldata.gatekeeper.sh/v1beta1",
                "kind": "ProviderRequest",
                "request": {"keys": ["d1", "d2", "dx"]},
            },
        )
        self.assertEqual(r.status_code, 200)
        items = {it["key"]: it for it in r.json()["response"]["items"]}
        self.assertEqual(items["d1"]["error"], "")
        self.assertEqual(items["d2"]["error"], "")
        d1_value = items["d1"]["value"]
        d2_value = items["d2"]["value"]
        for value in d1_value.values():
            self.assertIn(value, D1.values())
        for value in d2_value.values():
            self.assertIn(value, D2.values())
        self.assertIn("not found", items["dx"]["error"])

    def test_validate_empty_keys(self):
        r = self.client.post("/validate", json={"request": {"keys": []}})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["response"]["items"], [])
