import unittest

from fastapi.testclient import TestClient

from main import create_app
from src.config import Config

I1 = {"name": "i1", "contexts": ["Ford"]}
I2 = {"name": "i2", "contexts": []}

UPDATE_I1 = {"contexts": ["Ford", "Finance"]}

C_FORD_FERRARI = {"context_a": "Ford", "context_b": "Ferrari"}
C_BMW_MERCEDES = {"context_a": "BMW", "context_b": "Mercedes"}


def make_cfg(debug_mode: bool = True) -> Config:
    return Config(
        db_url="sqlite://",  # in-memory
        host="0.0.0.0",
        port=8443,
        tls_cert_file=None,
        tls_key_file=None,
        log_level="WARNING",
        debug_mode=debug_mode,
    )


class TestBase(unittest.TestCase):
    cfg = staticmethod(make_cfg)

    def setUp(self):
        self.app = create_app(self.cfg())
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def _create_i1(self):
        return self.client.post("/issuer-auths", json=I1)

    def _create_multiple(self):
        return self.client.post("/issuer-auths/batch", json=[I1, I2])

    def _create_conflict(self, pair=C_FORD_FERRARI):
        return self.client.post("/conflicts", json=pair)


class TestHealth(TestBase):
    def test_healthz(self):
        r = self.client.get("/healthz")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"status": "ok"})


class TestIssuerAuths(TestBase):
    def test_create_single(self):
        self.assertEqual(self._create_i1().status_code, 201)
        r = self.client.get("/issuer-auths/i1")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), I1)

    def test_create_multiple(self):
        r = self._create_multiple()
        self.assertEqual(r.status_code, 201)
        self.assertEqual(len(r.json()), 2)

    def test_query_existing(self):
        self._create_multiple()
        r = self.client.post("/issuer-auths/query", json={"keys": ["i1", "i2"]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()), 2)

    def test_query_missing_returns_404(self):
        self._create_i1()
        r = self.client.post("/issuer-auths/query", json={"keys": ["i1", "nope"]})
        self.assertEqual(r.status_code, 404)

    def test_duplicate_409(self):
        self._create_i1()
        self.assertEqual(self._create_i1().status_code, 409)

    def test_get_missing_404(self):
        self.assertEqual(self.client.get("/issuer-auths/nope").status_code, 404)

    def test_create_conflicting_contexts_409(self):
        self._create_conflict()
        r = self.client.post(
            "/issuer-auths", json={"name": "i1", "contexts": ["Ford", "Ferrari"]}
        )
        self.assertEqual(r.status_code, 409)
        self.assertIn("conflicts", r.json()["detail"])

    def test_update_replaces(self):
        self._create_i1()
        r = self.client.put("/issuer-auths/i1", json=UPDATE_I1)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["contexts"], UPDATE_I1["contexts"])

    def test_update_introducing_conflict_409(self):
        self._create_conflict()
        self._create_i1()
        r = self.client.put("/issuer-auths/i1", json={"contexts": ["Ford", "Ferrari"]})
        self.assertEqual(r.status_code, 409)

    def test_update_missing_404(self):
        r = self.client.put("/issuer-auths/nope", json=UPDATE_I1)
        self.assertEqual(r.status_code, 404)

    def test_delete(self):
        self._create_i1()
        self.assertEqual(self.client.delete("/issuer-auths/i1").status_code, 204)
        self.assertEqual(self.client.get("/issuer-auths/i1").status_code, 404)

    def test_delete_missing_404(self):
        self.assertEqual(self.client.delete("/issuer-auths/nope").status_code, 404)

    def test_delete_all(self):
        self._create_multiple()
        r = self.client.delete("/issuer-auths")
        self.assertEqual(r.status_code, 204)
        self.assertEqual(self.client.get("/issuer-auths/i1").status_code, 404)

    def test_delete_all_no_issuer_auths(self):
        self.assertEqual(self.client.delete("/issuer-auths").status_code, 404)

    def test_wall_check_missing_issuer_404(self):
        r = self.client.post("/issuer-auths/nope/wall-check", json={"contexts": []})
        self.assertEqual(r.status_code, 404)

    def test_wall_check_no_conflict(self):
        self._create_i1()  # auth(i1) = {Ford}
        r = self.client.post(
            "/issuer-auths/i1/wall-check", json={"contexts": ["Finance"]}
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"conflicts": []})

    def test_wall_check_conflict_found(self):
        self._create_conflict()  # Ford | Ferrari
        self._create_i1()  # auth(i1) = {Ford}
        r = self.client.post(
            "/issuer-auths/i1/wall-check", json={"contexts": ["Ferrari"]}
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            r.json(), {"conflicts": [{"context_a": "Ferrari", "context_b": "Ford"}]}
        )

    def test_wall_check_empty_lambda_no_conflict(self):
        self._create_i1()
        r = self.client.post("/issuer-auths/i1/wall-check", json={"contexts": []})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"conflicts": []})


class TestConflicts(TestBase):
    def test_create_and_list(self):
        r = self._create_conflict()
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json(), {"context_a": "Ferrari", "context_b": "Ford"})
        r = self.client.get("/conflicts")
        self.assertEqual(len(r.json()), 1)

    def test_create_irreflexive_rejected(self):
        r = self._create_conflict({"context_a": "Ford", "context_b": "Ford"})
        self.assertEqual(r.status_code, 422)

    def test_create_duplicate_409(self):
        self._create_conflict()
        r = self._create_conflict({"context_a": "Ferrari", "context_b": "Ford"})
        self.assertEqual(r.status_code, 409)

    def test_create_conflict_held_by_issuer_auth_409(self):
        self.client.post(
            "/issuer-auths", json={"name": "i1", "contexts": ["Ford", "Ferrari"]}
        )
        r = self._create_conflict()
        self.assertEqual(r.status_code, 409)
        self.assertIn("i1", r.json()["detail"]["issuers"])

    def test_delete(self):
        self._create_conflict()
        r = self.client.delete("/conflicts/Ford/Ferrari")
        self.assertEqual(r.status_code, 204)
        self.assertEqual(self.client.get("/conflicts").json(), [])

    def test_delete_missing_404(self):
        r = self.client.delete("/conflicts/Ford/Ferrari")
        self.assertEqual(r.status_code, 404)

    def test_delete_same_context_422(self):
        r = self.client.delete("/conflicts/Ford/Ford")
        self.assertEqual(r.status_code, 422)

    def test_delete_all(self):
        self._create_conflict(C_FORD_FERRARI)
        self._create_conflict(C_BMW_MERCEDES)
        r = self.client.delete("/conflicts")
        self.assertEqual(r.status_code, 204)
        self.assertEqual(self.client.get("/conflicts").json(), [])

    def test_get_for_context(self):
        self._create_conflict(C_FORD_FERRARI)
        self._create_conflict(C_BMW_MERCEDES)
        r = self.client.get("/conflicts/Ford")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [{"context_a": "Ferrari", "context_b": "Ford"}])

    def test_get_for_context_no_match_returns_empty_list(self):
        r = self.client.get("/conflicts/Finance")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

    def test_create_batch(self):
        r = self.client.post("/conflicts/batch", json=[C_FORD_FERRARI, C_BMW_MERCEDES])
        self.assertEqual(r.status_code, 201)
        self.assertEqual(len(r.json()), 2)
        self.assertEqual(len(self.client.get("/conflicts").json()), 2)

    def test_create_batch_atomic_on_duplicate(self):
        self._create_conflict(C_FORD_FERRARI)
        r = self.client.post("/conflicts/batch", json=[C_BMW_MERCEDES, C_FORD_FERRARI])
        self.assertEqual(r.status_code, 409)
        # BMW|Mercedes must not have been committed either.
        self.assertEqual(len(self.client.get("/conflicts").json()), 1)

    def test_create_batch_held_by_issuer_auth_409(self):
        self.client.post(
            "/issuer-auths", json={"name": "i1", "contexts": ["Ford", "Ferrari"]}
        )
        r = self.client.post("/conflicts/batch", json=[C_FORD_FERRARI])
        self.assertEqual(r.status_code, 409)


class TestProvider(TestBase):
    def test_validate_existing_and_missing(self):
        self._create_multiple()
        r = self.client.post(
            "/issuer-auths/validate",
            json={
                "apiVersion": "externaldata.gatekeeper.sh/v1beta1",
                "kind": "ProviderRequest",
                "request": {"keys": ["i1", "i2", "ix"]},
            },
        )
        self.assertEqual(r.status_code, 200)
        items = {it["key"]: it for it in r.json()["response"]["items"]}
        self.assertEqual(items["i1"]["error"], "")
        self.assertEqual(items["i1"]["value"]["contexts"], I1["contexts"])
        self.assertEqual(items["i2"]["value"]["contexts"], I2["contexts"])
        self.assertIn("not found", items["ix"]["error"])

    def test_validate_empty_keys(self):
        r = self.client.post("/issuer-auths/validate", json={"request": {"keys": []}})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["response"]["items"], [])


class TestIssuerAuthsDebugModeOff(TestBase):
    """
    Regression test for the config-wiring bug: verify_debug_mode must
    read the config this app was actually built with (via get_config ->
    app.state.config), not a module-level Config.from_env() snapshot
    that would ignore this override entirely.
    """

    cfg = staticmethod(lambda: make_cfg(debug_mode=False))

    def test_update_endpoint_hidden_when_debug_mode_off(self):
        self._create_i1()
        r = self.client.put("/issuer-auths/i1", json=UPDATE_I1)
        self.assertEqual(r.status_code, 404)
