import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from main import create_app
from src.config import Config


def make_client(tmpdir: str) -> TestClient:
    cfg = Config(
        database_path=os.path.join(tmpdir, "db.json"),
        seed_path="",  # start empty, no seed
        host="0.0.0.0",
        port=8443,
        log_level="INFO",
    )
    return TestClient(create_app(cfg))


class TestHealth(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.client = make_client(self.tmp)

    def test_healthz(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"status": "ok"})


class TestCrud(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.client = make_client(self.tmp)

    def _create_d1(self):
        return self.client.post(
            "/datasets",
            json={
                "name": "d1",
                "requirements": {"security": 2, "computation": 1},
                "nodes": ["kind-worker"],
                "owner": "org-a",
                "category": "medical",
            },
        )

    def test_create_and_get(self):
        r = self._create_d1()
        self.assertEqual(r.status_code, 201)

        r = self.client.get("/datasets/d1")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["requirements"], {"security": 2, "computation": 1})
        self.assertEqual(body["nodes"], ["kind-worker"])

    def test_create_duplicate_conflicts(self):
        self._create_d1()
        r = self._create_d1()
        self.assertEqual(r.status_code, 409)

    def test_get_missing_404(self):
        r = self.client.get("/datasets/nope")
        self.assertEqual(r.status_code, 404)

    def test_list(self):
        self._create_d1()
        r = self.client.get("/datasets")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()), 1)

    def test_update_replaces(self):
        self._create_d1()
        r = self.client.put(
            "/datasets/d1",
            json={
                "requirements": {"security": 3},
                "nodes": [],
                "owner": "org-a",
                "category": "medical",
            },
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["requirements"], {"security": 3})
        self.assertEqual(r.json()["nodes"], [])

    def test_update_missing_404(self):
        r = self.client.put("/datasets/nope", json={"requirements": {}, "nodes": []})
        self.assertEqual(r.status_code, 404)

    def test_delete(self):
        self._create_d1()
        r = self.client.delete("/datasets/d1")
        self.assertEqual(r.status_code, 204)
        self.assertEqual(self.client.get("/datasets/d1").status_code, 404)

    def test_delete_missing_404(self):
        r = self.client.delete("/datasets/nope")
        self.assertEqual(r.status_code, 404)


class TestValidateEDP(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.client = make_client(self.tmp)
        self.client.post(
            "/datasets",
            json={
                "name": "d1",
                "requirements": {"security": 2, "computation": 1},
                "nodes": ["kind-worker"],
                "owner": "org-a",
                "category": "medical",
            },
        )

    def _validate(self, keys):
        return self.client.post(
            "/validate",
            json={
                "apiVersion": "externaldata.gatekeeper.sh/v1beta1",
                "kind": "ProviderRequest",
                "request": {"keys": keys},
            },
        )

    def test_existing_dataset_returns_metadata(self):
        r = self._validate(["d1"])
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["kind"], "ProviderResponse")
        items = body["response"]["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["key"], "d1")
        self.assertEqual(items[0]["error"], "")
        self.assertEqual(
            items[0]["value"]["requirements"], {"security": 2, "computation": 1}
        )

    def test_missing_dataset_returns_error(self):
        r = self._validate(["dX"])
        items = r.json()["response"]["items"]
        self.assertEqual(items[0]["key"], "dX")
        self.assertIn("not found", items[0]["error"])

    def test_mixed_keys(self):
        r = self._validate(["d1", "dX"])
        items = {it["key"]: it for it in r.json()["response"]["items"]}
        self.assertEqual(items["d1"]["error"], "")
        self.assertNotEqual(items["dX"]["error"], "")

    def test_empty_keys(self):
        r = self._validate([])
        self.assertEqual(r.json()["response"]["items"], [])


if __name__ == "__main__":
    unittest.main()
