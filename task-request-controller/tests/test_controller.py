import json
import unittest
from unittest.mock import MagicMock

from kubernetes.client.exceptions import ApiException

from src.config import Config
from src.controller import Controller, TASK_REQUEST_LABEL, BETA_STAR_ANNOTATION
from src.dataset_service import (
    DatasetNotFoundError,
    DatasetServiceError,
)

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def make_config() -> Config:
    return Config(
        group="policydriven.unimi.it",
        version="v1alpha1",
        task_requests_plural="taskrequests",
        task_namespace="compute",
        dataset_service_url="https://dataset-service.svc",
        ca_cert_file=None,
        job_label_prefix="scheduling.task.policydriven.unimi.it",
        job_annotation_prefix="scheduling.task.policydriven.unimi.it",
        log_level="WARNING",
    )


def make_logger() -> MagicMock:
    log = MagicMock()
    log.info = log.warning = log.error = log.debug = MagicMock()
    return log


def make_ctrl(dataset_service=None) -> tuple[Controller, MagicMock, MagicMock]:
    batch_v1 = MagicMock()
    custom_api = MagicMock()
    if dataset_service is None:
        dataset_service = MagicMock()
    ctrl = Controller(
        batch_v1=batch_v1,
        custom_api=custom_api,
        config=make_config(),
        dataset_service=dataset_service,
    )
    return ctrl, batch_v1, custom_api


def make_body(name="t1", uid="uid-abc", phase=None, requirements=None, datasets=None):
    body = {
        "metadata": {"name": name, "namespace": "compute", "uid": uid},
        "spec": {
            "requirements": requirements or {},
            "datasets": datasets or [],
        },
        "status": {},
    }
    if phase is not None:
        body["status"]["phase"] = phase
    return body


# ------------------------------------------------------------------
# Controller._compute_beta_star tests
# ------------------------------------------------------------------


class TestComputeBetaStar(unittest.TestCase):
    def setUp(self):
        self.dataset_client = MagicMock()
        self.ctrl, _, _ = make_ctrl(self.dataset_client)

    def test_no_datasets(self):
        result = self.ctrl._compute_beta_star({"security": 2, "computation": 1}, [])
        self.assertEqual(result, {"security": 2, "computation": 1})

    def test_dataset_raises_existing_requirement(self):
        self.dataset_client.get_dataset.return_value = {
            "requirements": {"security": 2},
        }
        result = self.ctrl._compute_beta_star({"security": 1}, ["d1"])
        self.assertEqual(result, {"security": 2})

    def test_task_requirement_prevails(self):
        self.dataset_client.get_dataset.return_value = {
            "requirements": {"security": 1},
        }
        result = self.ctrl._compute_beta_star({"security": 3}, ["d1"])
        self.assertEqual(result, {"security": 3})

    def test_dataset_adds_new_property(self):
        self.dataset_client.get_dataset.return_value = {
            "requirements": {"computation": 3},
        }
        result = self.ctrl._compute_beta_star({"security": 1}, ["d1"])
        self.assertEqual(result, {"security": 1, "computation": 3})

    def test_multiple_datasets_lub(self):
        self.dataset_client.get_dataset.side_effect = [
            {"requirements": {"security": 2, "computation": 1}},
            {"requirements": {"security": 1, "computation": 3}},
        ]
        result = self.ctrl._compute_beta_star(
            {"security": 1, "computation": 2}, ["d1", "d2"]
        )
        self.assertEqual(result, {"security": 2, "computation": 3})

    def test_empty_requirements_and_no_datasets(self):
        result = self.ctrl._compute_beta_star({}, [])
        self.assertEqual(result, {})

    def test_dataset_with_empty_requirements(self):
        self.dataset_client.get_dataset.return_value = {"requirements": {}}
        result = self.ctrl._compute_beta_star({"security": 2}, ["d1"])
        self.assertEqual(result, {"security": 2})


# ------------------------------------------------------------------
# Controller._build_job tests
# ------------------------------------------------------------------


class TestBuildJob(unittest.TestCase):
    def setUp(self):
        self.ctrl, _, _ = make_ctrl()

    def _build(self, beta_star):
        return self.ctrl._build_job("t1", "compute", beta_star, "uid-123")

    def test_owner_reference(self):
        job = self._build({"security": 2})
        owner = job["metadata"]["ownerReferences"][0]
        self.assertEqual(owner["kind"], "TaskRequest")
        self.assertEqual(owner["name"], "t1")
        self.assertEqual(owner["uid"], "uid-123")
        self.assertTrue(owner["controller"])
        self.assertTrue(owner["blockOwnerDeletion"])

    def test_task_request_label(self):
        job = self._build({"security": 2})
        self.assertEqual(job["metadata"]["labels"][TASK_REQUEST_LABEL], "t1")

    def test_beta_star_annotation(self):
        beta_star = {"security": 2, "computation": 1}
        job = self._build(beta_star)
        annotation = json.loads(job["metadata"]["annotations"][BETA_STAR_ANNOTATION])
        self.assertEqual(annotation, beta_star)

    def test_node_affinity_gt_operator(self):
        job = self._build({"security": 2})
        exprs = job["spec"]["template"]["spec"]["affinity"]["nodeAffinity"][
            "requiredDuringSchedulingIgnoredDuringExecution"
        ]["nodeSelectorTerms"][0]["matchExpressions"]
        self.assertEqual(len(exprs), 1)
        self.assertEqual(
            exprs[0]["key"], "property.node.policydriven.unimi.it/security"
        )
        self.assertEqual(exprs[0]["operator"], "Gt")
        self.assertEqual(exprs[0]["values"], ["1"])

    def test_node_affinity_multiple_properties(self):
        job = self._build({"security": 2, "computation": 3})
        exprs = job["spec"]["template"]["spec"]["affinity"]["nodeAffinity"][
            "requiredDuringSchedulingIgnoredDuringExecution"
        ]["nodeSelectorTerms"][0]["matchExpressions"]
        keys = {e["key"] for e in exprs}
        self.assertIn("property.node.policydriven.unimi.it/security", keys)
        self.assertIn("property.node.policydriven.unimi.it/computation", keys)

    def test_zero_level_excluded_from_affinity(self):
        job = self._build({"security": 0, "computation": 2})
        exprs = job["spec"]["template"]["spec"]["affinity"]["nodeAffinity"][
            "requiredDuringSchedulingIgnoredDuringExecution"
        ]["nodeSelectorTerms"][0]["matchExpressions"]
        keys = [e["key"] for e in exprs]
        self.assertNotIn("property.node.policydriven.unimi.it/security", keys)

    def test_all_zero_levels_no_affinity(self):
        job = self._build({"security": 0})
        self.assertNotIn("affinity", job["spec"]["template"]["spec"])

    def test_empty_beta_star_no_affinity(self):
        job = self._build({})
        self.assertNotIn("affinity", job["spec"]["template"]["spec"])

    def test_backoff_limit_zero(self):
        job = self._build({"security": 1})
        self.assertEqual(job["spec"]["backoffLimit"], 0)

    def test_restart_policy_never(self):
        job = self._build({"security": 1})
        self.assertEqual(job["spec"]["template"]["spec"]["restartPolicy"], "Never")


# ------------------------------------------------------------------
# Controller.reconcile tests
# ------------------------------------------------------------------


class TestReconcile(unittest.TestCase):
    def setUp(self):
        self.dataset_client = MagicMock()
        self.ctrl, self.batch_v1, self.custom_api = make_ctrl(self.dataset_client)
        self.logger = make_logger()

    def _set_status_calls(self):
        return self.custom_api.patch_namespaced_custom_object_status.call_args_list

    def test_terminal_succeeded_is_skipped(self):
        body = make_body(phase="Succeeded")
        self.ctrl.reconcile("t1", "compute", body, self.logger)
        self.batch_v1.create_namespaced_job.assert_not_called()
        self.custom_api.patch_namespaced_custom_object_status.assert_not_called()

    def test_terminal_failed_is_skipped(self):
        body = make_body(phase="Failed")
        self.ctrl.reconcile("t1", "compute", body, self.logger)
        self.batch_v1.create_namespaced_job.assert_not_called()

    def test_scheduled_triggers_job_sync(self):
        body = make_body(phase="Scheduled")
        mock_job = MagicMock()
        mock_job.status.conditions = None
        self.batch_v1.read_namespaced_job.return_value = mock_job

        self.ctrl.reconcile("t1", "compute", body, self.logger)

        self.batch_v1.read_namespaced_job.assert_called_once_with("t1", "compute")
        self.batch_v1.create_namespaced_job.assert_not_called()

    def test_new_task_request_full_reconciliation(self):
        body = make_body(requirements={"security": 1}, datasets=["d1"])
        self.dataset_client.get_dataset.return_value = {
            "requirements": {"security": 2, "computation": 1}
        }

        self.ctrl.reconcile("t1", "compute", body, self.logger)

        # Job must be created
        self.batch_v1.create_namespaced_job.assert_called_once()
        job_arg = self.batch_v1.create_namespaced_job.call_args[0][1]
        self.assertEqual(job_arg["metadata"]["name"], "t1")

        # Status must progress: Pending → Scheduled
        calls = self._set_status_calls()
        phases = [c[1]["body"]["status"]["phase"] for c in calls]
        self.assertEqual(phases, ["Pending", "Scheduled"])

    def test_dataset_not_found_sets_failed(self):
        body = make_body(datasets=["missing"])
        self.dataset_client.get_dataset.side_effect = DatasetNotFoundError(
            "Dataset not found: 'missing'"
        )

        self.ctrl.reconcile("t1", "compute", body, self.logger)

        self.batch_v1.create_namespaced_job.assert_not_called()
        calls = self._set_status_calls()
        phases = [c[1]["body"]["status"]["phase"] for c in calls]
        self.assertIn("Failed", phases)

    def test_dataset_service_error_raises_temporary(self):
        import kopf

        body = make_body(datasets=["d1"])
        self.dataset_client.get_dataset.side_effect = DatasetServiceError("unreachable")

        with self.assertRaises(kopf.TemporaryError):
            self.ctrl.reconcile("t1", "compute", body, self.logger)

    def test_job_already_exists_is_idempotent(self):
        body = make_body(requirements={"security": 1})
        conflict = ApiException(status=409, reason="Conflict")
        self.batch_v1.create_namespaced_job.side_effect = conflict

        self.ctrl.reconcile("t1", "compute", body, self.logger)

        # Status should still be set to Scheduled despite the 409
        calls = self._set_status_calls()
        phases = [c[1]["body"]["status"]["phase"] for c in calls]
        self.assertIn("Scheduled", phases)

    def test_beta_star_annotation_in_job(self):
        body = make_body(requirements={"security": 1}, datasets=["d1"])
        self.dataset_client.get_dataset.return_value = {"requirements": {"security": 2}}

        self.ctrl.reconcile("t1", "compute", body, self.logger)

        job_arg = self.batch_v1.create_namespaced_job.call_args[0][1]
        annotation = json.loads(
            job_arg["metadata"]["annotations"][BETA_STAR_ANNOTATION]
        )
        self.assertEqual(annotation["security"], 2)


# ------------------------------------------------------------------
# Controller.sync_job_status tests
# ------------------------------------------------------------------


class TestSyncJobStatus(unittest.TestCase):
    def setUp(self):
        self.ctrl, _, self.custom_api = make_ctrl()
        self.logger = make_logger()

    def _call_sync(self, conditions):
        status = {"conditions": conditions}
        self.ctrl.sync_job_status("t1", "compute", status, self.logger)

    def _patched_phase(self):
        return self.custom_api.patch_namespaced_custom_object_status.call_args[1][
            "body"
        ]["status"]["phase"]

    def test_job_complete_sets_succeeded(self):
        self._call_sync([{"type": "Complete", "status": "True"}])
        self.assertEqual(self._patched_phase(), "Succeeded")

    def test_job_failed_sets_failed(self):
        self._call_sync(
            [{"type": "Failed", "status": "True", "message": "BackoffLimitExceeded"}]
        )
        self.assertEqual(self._patched_phase(), "Failed")

    def test_job_running_no_update(self):
        self._call_sync([])
        self.custom_api.patch_namespaced_custom_object_status.assert_not_called()

    def test_empty_status_no_update(self):
        self.ctrl.sync_job_status("t1", "compute", {}, self.logger)
        self.custom_api.patch_namespaced_custom_object_status.assert_not_called()

    def test_none_status_no_update(self):
        self.ctrl.sync_job_status("t1", "compute", None, self.logger)
        self.custom_api.patch_namespaced_custom_object_status.assert_not_called()

    def test_v1_job_status_object_complete(self):
        mock_status = MagicMock()
        mock_cond = MagicMock()
        mock_cond.type = "Complete"
        mock_cond.status = "True"
        mock_status.conditions = [mock_cond]

        self.ctrl.sync_job_status("t1", "compute", mock_status, self.logger)
        self.assertEqual(self._patched_phase(), "Succeeded")
