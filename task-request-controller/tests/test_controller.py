import json
import unittest
from unittest.mock import MagicMock

from kubernetes import client
from kubernetes.client.exceptions import ApiException

from src.config import (
    Config,
    TASK_REQUEST_KIND_DEFAULT,
    JOB_LABEL_PREFIX_DEFAULT,
    JOB_ANNOTATION_PREFIX_DEFAULT,
    TASK_REQUEST_REF_LABEL_DEFAULT,
    BETA_STAR_ANNOTATION_DEFAULT,
    DATASETS_ANNOTATION_DEFAULT,
)
from src.controller import (
    Controller,
    COMPLETE_PHASE,
    FAILURE_PHASE,
    SCHEDULED_PHASE,
    PENDING_PHASE,
)
from src.dataset_service import DatasetNotFoundError, DatasetServiceError


def make_config() -> Config:
    return Config(
        group="policydriven.unimi.it",
        version="v1alpha1",
        task_requests_plural="taskrequests",
        task_namespace="compute",
        dataset_service_url="https://dataset-service.svc",
        ca_cert_file=None,
        task_request_kind=TASK_REQUEST_KIND_DEFAULT,
        job_label_prefix=JOB_LABEL_PREFIX_DEFAULT,
        job_annotation_prefix=JOB_ANNOTATION_PREFIX_DEFAULT,
        task_request_ref_label=TASK_REQUEST_REF_LABEL_DEFAULT,
        beta_star_annotation=BETA_STAR_ANNOTATION_DEFAULT,
        datasets_annotation=DATASETS_ANNOTATION_DEFAULT,
        log_level="WARNING",
    )


def make_logger() -> MagicMock:
    log = MagicMock()
    log.info = log.warning = log.error = log.debug = MagicMock()
    return log


def make_job_condition(
    type: str, status: str = "True", message: str = ""
) -> client.V1JobCondition:
    return client.V1JobCondition(type=type, status=status, message=message or None)


class ControllerTestBase(unittest.TestCase):
    """Shared setup for all Controller tests."""

    def setUp(self):
        self.batch_v1 = MagicMock()
        self.custom_api = MagicMock()
        self.dataset_service = MagicMock()
        self.cfg = make_config()
        self.ctrl = Controller(
            batch_v1=self.batch_v1,
            custom_api=self.custom_api,
            dataset_service=self.dataset_service,
            config=self.cfg,
        )
        self.logger = make_logger()

    def make_body(
        self, name="t1", uid="uid-abc", phase=None, requirements=None, datasets=None
    ):
        body = {
            "metadata": {"name": name, "namespace": "compute", "uid": uid},
            "spec": {"requirements": requirements or {}, "datasets": datasets or []},
            "status": {},
        }
        if phase is not None:
            body["status"]["phase"] = phase
        return body

    def do_reconcile(self, **kwargs):
        body = self.make_body(**kwargs)
        self.ctrl.reconcile(body["metadata"]["name"], "compute", body, self.logger)
        return body

    def patched_phases(self) -> list[str]:
        return [
            c[1]["body"]["status"]["phase"]
            for c in self.custom_api.patch_namespaced_custom_object_status.call_args_list
        ]

    def created_job(self) -> client.V1Job:
        return self.batch_v1.create_namespaced_job.call_args[0][1]

    def job_annotation(self, key_suffix: str) -> str:
        key = f"{self.cfg.job_annotation_prefix}/{key_suffix}"
        return self.created_job().metadata.annotations[key]


class TestBuildJob(ControllerTestBase):
    def setUp(self):
        super().setUp()
        self.job = self.ctrl._build_job(
            "t1", "compute", {"security": 2}, ["d1"], "uid-123"
        )

    def test_returns_v1job_with_correct_metadata(self):
        self.assertIsInstance(self.job, client.V1Job)
        self.assertEqual(self.job.metadata.name, "t1")
        self.assertEqual(self.job.metadata.namespace, "compute")

    def test_task_request_label_present(self):
        key = f"{self.cfg.job_label_prefix}/{TASK_REQUEST_REF_LABEL_DEFAULT}"
        self.assertEqual(self.job.metadata.labels[key], "t1")

    def test_scheduling_annotations_present(self):
        annotations = self.job.metadata.annotations
        beta_key = f"{self.cfg.job_annotation_prefix}/{BETA_STAR_ANNOTATION_DEFAULT}"
        datasets_key = f"{self.cfg.job_annotation_prefix}/{DATASETS_ANNOTATION_DEFAULT}"
        self.assertEqual(json.loads(annotations[beta_key]), {"security": 2})
        self.assertEqual(json.loads(annotations[datasets_key]), ["d1"])

    def test_owner_reference(self):
        ref = self.job.metadata.owner_references[0]
        self.assertEqual(ref.kind, TASK_REQUEST_KIND_DEFAULT)
        self.assertEqual(ref.uid, "uid-123")
        self.assertTrue(ref.controller)
        self.assertTrue(ref.block_owner_deletion)

    def test_spec_constraints(self):
        spec = self.job.spec
        pod_spec = spec.template.spec
        self.assertEqual(spec.backoff_limit, 0)
        self.assertEqual(pod_spec.restart_policy, "Never")
        self.assertEqual(len(pod_spec.containers), 1)
        self.assertEqual(pod_spec.containers[0].name, "task")


class TestReconcile(ControllerTestBase):
    def setUp(self):
        super().setUp()
        self.dataset_service.compute_effective_beta.return_value = {"security": 2}

    def test_terminal_phases_are_no_op(self):
        for phase in (COMPLETE_PHASE, FAILURE_PHASE):
            with self.subTest(phase=phase):
                self.do_reconcile(phase=phase)
                self.batch_v1.create_namespaced_job.assert_not_called()
                self.custom_api.patch_namespaced_custom_object_status.assert_not_called()

    def test_scheduled_syncs_job_without_creating_new_one(self):
        mock_job = MagicMock()
        mock_job.status.conditions = None
        self.batch_v1.read_namespaced_job.return_value = mock_job
        self.do_reconcile(phase=SCHEDULED_PHASE)
        self.batch_v1.read_namespaced_job.assert_called_once_with("t1", "compute")
        self.batch_v1.create_namespaced_job.assert_not_called()

    def test_full_reconcile_creates_job_and_sets_phases(self):
        self.do_reconcile(requirements={"security": 1}, datasets=["d1", "d2"])
        self.batch_v1.create_namespaced_job.assert_called_once()
        self.assertIsInstance(self.created_job(), client.V1Job)
        self.assertEqual(self.patched_phases(), [PENDING_PHASE, SCHEDULED_PHASE])

    def test_full_reconcile_annotations_reflect_beta_star_and_datasets(self):
        self.dataset_service.compute_effective_beta.return_value = {
            "security": 2,
            "computation": 3,
        }
        self.do_reconcile(datasets=["d1", "d2"])
        self.assertEqual(
            json.loads(self.job_annotation(BETA_STAR_ANNOTATION_DEFAULT)),
            {"security": 2, "computation": 3},
        )
        self.assertEqual(
            json.loads(self.job_annotation(DATASETS_ANNOTATION_DEFAULT)), ["d1", "d2"]
        )

    def test_dataset_not_found_sets_failed_without_creating_job(self):
        self.dataset_service.compute_effective_beta.side_effect = DatasetNotFoundError(
            "missing"
        )
        self.do_reconcile(datasets=["missing"])
        self.batch_v1.create_namespaced_job.assert_not_called()
        self.assertIn(FAILURE_PHASE, self.patched_phases())
        self.assertNotIn(SCHEDULED_PHASE, self.patched_phases())

    def test_dataset_service_error_raises_temporary(self):
        import kopf

        self.dataset_service.compute_effective_beta.side_effect = DatasetServiceError(
            "unreachable"
        )
        with self.assertRaises(kopf.TemporaryError):
            self.do_reconcile()

    def test_job_conflict_409_is_idempotent(self):
        self.batch_v1.create_namespaced_job.side_effect = ApiException(status=409)
        self.do_reconcile()
        self.assertIn(SCHEDULED_PHASE, self.patched_phases())

    def test_job_invalid_422_sets_failed(self):
        err = ApiException(status=422)
        err.reason = "Unprocessable Entity"
        self.batch_v1.create_namespaced_job.side_effect = err
        self.do_reconcile()
        self.assertIn(FAILURE_PHASE, self.patched_phases())
        self.assertNotIn(SCHEDULED_PHASE, self.patched_phases())

    def test_job_server_error_raises_temporary(self):
        import kopf

        self.batch_v1.create_namespaced_job.side_effect = ApiException(status=500)
        with self.assertRaises(kopf.TemporaryError):
            self.do_reconcile()


class TestExtractConditions(ControllerTestBase):
    def test_none_and_empty_inputs_return_empty(self):
        self.assertEqual(self.ctrl._extract_conditions(None), [])
        self.assertEqual(self.ctrl._extract_conditions({}), [])
        self.assertEqual(self.ctrl._extract_conditions({"active": 1}), [])

    def test_dict_maps_all_fields_to_v1_job_condition(self):
        status = {
            "conditions": [
                {
                    "type": "Complete",
                    "status": "True",
                    "message": "done",
                    "reason": "CompletionsReached",
                    "lastProbeTime": "2026-01-01T00:00:00Z",
                    "lastTransitionTime": "2026-01-01T00:00:01Z",
                }
            ]
        }
        cond = self.ctrl._extract_conditions(status)[0]
        self.assertIsInstance(cond, client.V1JobCondition)
        self.assertEqual(cond.type, "Complete")
        self.assertEqual(cond.status, "True")
        self.assertEqual(cond.message, "done")
        self.assertEqual(cond.reason, "CompletionsReached")
        self.assertEqual(cond.last_probe_time, "2026-01-01T00:00:00Z")
        self.assertEqual(cond.last_transition_time, "2026-01-01T00:00:01Z")

    def test_v1_job_status_returned_directly(self):
        expected = [make_job_condition("Complete"), make_job_condition("Failed")]
        mock_status = MagicMock(spec=client.V1JobStatus)
        mock_status.conditions = expected
        self.assertEqual(self.ctrl._extract_conditions(mock_status), expected)

    def test_v1_job_status_none_conditions_returns_empty(self):
        mock_status = MagicMock(spec=client.V1JobStatus)
        mock_status.conditions = None
        self.assertEqual(self.ctrl._extract_conditions(mock_status), [])


class TestSyncJobStatus(ControllerTestBase):
    def _sync(self, *conditions: client.V1JobCondition):
        status = {
            "conditions": [
                {"type": c.type, "status": c.status, "message": c.message}
                for c in conditions
            ]
        }
        self.ctrl.sync_job_status("t1", "compute", status, self.logger)

    def _patched_phase(self) -> str:
        return self.custom_api.patch_namespaced_custom_object_status.call_args[1][
            "body"
        ]["status"]["phase"]

    def test_complete_condition_sets_complete_phase(self):
        self._sync(make_job_condition(COMPLETE_PHASE, message="ok"))
        self.assertEqual(self._patched_phase(), COMPLETE_PHASE)

    def test_failed_condition_sets_failed_phase(self):
        self._sync(make_job_condition(FAILURE_PHASE, message="OOMKilled"))
        self.assertEqual(self._patched_phase(), FAILURE_PHASE)
        body = self.custom_api.patch_namespaced_custom_object_status.call_args[1][
            "body"
        ]
        self.assertEqual(body["status"]["message"], "OOMKilled")

    def test_unknown_or_pending_conditions_produce_no_update(self):
        for cond in [
            make_job_condition("SuccessCriteriaMet"),
            make_job_condition(COMPLETE_PHASE, status="False"),
        ]:
            with self.subTest(type=cond.type, status=cond.status):
                self._sync(cond)
                self.custom_api.patch_namespaced_custom_object_status.assert_not_called()

    def test_none_and_empty_status_produce_no_update(self):
        self.ctrl.sync_job_status("t1", "compute", None, self.logger)
        self.ctrl.sync_job_status("t1", "compute", {}, self.logger)
        self.custom_api.patch_namespaced_custom_object_status.assert_not_called()

    def test_complete_fires_after_success_criteria_met(self):
        # Kubernetes emits SuccessCriteriaMet before Complete; only Complete triggers.
        self._sync(
            make_job_condition("SuccessCriteriaMet"), make_job_condition(COMPLETE_PHASE)
        )
        self.assertEqual(self._patched_phase(), COMPLETE_PHASE)


class TestStatusAndSyncExceptions(ControllerTestBase):
    def test_set_status_404_and_422_do_not_raise(self):
        for status_code in (404, 422):
            with self.subTest(status=status_code):
                err = ApiException(status=status_code)
                err.reason = "test"
                self.custom_api.patch_namespaced_custom_object_status.side_effect = err
                self.ctrl._set_status(
                    "compute", "t1", SCHEDULED_PHASE, "", "t1", self.logger
                )

    def test_set_status_other_errors_reraise(self):
        self.custom_api.patch_namespaced_custom_object_status.side_effect = (
            ApiException(status=500)
        )
        with self.assertRaises(ApiException):
            self.ctrl._set_status(
                "compute", "t1", SCHEDULED_PHASE, "", "t1", self.logger
            )

    def test_sync_from_job_handles_api_errors_gracefully(self):
        for status_code in (404, 503):
            with self.subTest(status=status_code):
                self.batch_v1.read_namespaced_job.side_effect = ApiException(
                    status=status_code
                )
                self.ctrl._sync_from_job("t1", "compute", self.logger)
                self.custom_api.patch_namespaced_custom_object_status.assert_not_called()

    def test_sync_from_job_sets_complete_on_finished_job(self):
        mock_job = MagicMock()
        mock_job.status.conditions = [make_job_condition(COMPLETE_PHASE)]
        self.batch_v1.read_namespaced_job.return_value = mock_job
        self.ctrl._sync_from_job("t1", "compute", self.logger)
        phase = self.custom_api.patch_namespaced_custom_object_status.call_args[1][
            "body"
        ]["status"]["phase"]
        self.assertEqual(phase, COMPLETE_PHASE)
