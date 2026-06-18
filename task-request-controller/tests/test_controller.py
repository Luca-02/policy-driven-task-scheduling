import json
import unittest
from unittest.mock import MagicMock

from kubernetes import client
from kubernetes.client.exceptions import ApiException

from src.config import (
    Config,
    DATASET_SERVICE_URL_DEFAULT,
    GEOGRAPHICAL_GROUPS_PLURAL_DEFAULT,
    GROUP_DEFAULT,
    NODE_TOPOLOGY_LOCATION_LABEL_DEFAULT,
    TASK_NAMESPACE_DEFAULT,
    TASK_REQUESTS_PLURAL_DEFAULT,
    VERSION_DEFAULT,
    TASK_REQUEST_KIND_DEFAULT,
    JOB_LABEL_PREFIX_DEFAULT,
    JOB_ANNOTATION_PREFIX_DEFAULT,
    TASK_REQUEST_REF_LABEL_DEFAULT,
    BETA_STAR_ANNOTATION_DEFAULT,
    GEO_STAR_ANNOTATION_DEFAULT,
    DATASETS_ANNOTATION_DEFAULT,
    NODE_PROPERTY_PREFIX_DEFAULT,
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
        group=GROUP_DEFAULT,
        version=VERSION_DEFAULT,
        task_requests_plural=TASK_REQUESTS_PLURAL_DEFAULT,
        geographical_groups_plural=GEOGRAPHICAL_GROUPS_PLURAL_DEFAULT,
        task_namespace=TASK_NAMESPACE_DEFAULT,
        dataset_service_url=DATASET_SERVICE_URL_DEFAULT,
        ca_cert_file=None,
        task_request_kind=TASK_REQUEST_KIND_DEFAULT,
        job_label_prefix=JOB_LABEL_PREFIX_DEFAULT,
        job_annotation_prefix=JOB_ANNOTATION_PREFIX_DEFAULT,
        task_request_ref_label=TASK_REQUEST_REF_LABEL_DEFAULT,
        beta_star_annotation=BETA_STAR_ANNOTATION_DEFAULT,
        geo_star_annotation=GEO_STAR_ANNOTATION_DEFAULT,
        datasets_annotation=DATASETS_ANNOTATION_DEFAULT,
        node_property_prefix=NODE_PROPERTY_PREFIX_DEFAULT,
        node_topology_location_label=NODE_TOPOLOGY_LOCATION_LABEL_DEFAULT,
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
        # By default, no datasets are requested and the dataset service is
        # never contacted: _get_all_datasets([]) -> [].
        self.dataset_service.get_all_datasets.return_value = []

    def make_body(
        self,
        name="t1",
        uid="uid-abc",
        phase=None,
        requirements=None,
        datasets=None,
        geo=None,
    ):
        body = {
            "metadata": {"name": name, "namespace": "compute", "uid": uid},
            "spec": {
                "requirements": requirements or {},
                "datasets": datasets or [],
            },
            "status": {},
        }
        if geo is not None:
            body["spec"]["geo"] = geo
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

    def last_failure_message(self) -> str:
        for c in reversed(
            self.custom_api.patch_namespaced_custom_object_status.call_args_list
        ):
            if c[1]["body"]["status"]["phase"] == FAILURE_PHASE:
                return c[1]["body"]["status"]["message"]
        return ""

    def created_job(self) -> client.V1Job:
        return self.batch_v1.create_namespaced_job.call_args[0][1]

    def job_annotation(self, key_suffix: str) -> str | None:
        key = f"{self.cfg.job_annotation_prefix}/{key_suffix}"
        return self.created_job().metadata.annotations.get(key)

    def load_geo_groups(self, *groups: tuple[str, list[str], list[str]]):
        """groups: (name, locations, includes) tuples."""
        for name, locations, includes in groups:
            self.ctrl.on_geographical_group_created_or_updated(
                name, {"locations": locations, "includes": includes}, self.logger
            )


class TestReconcile(ControllerTestBase):
    def setUp(self):
        super().setUp()
        self.dataset_service.get_all_datasets.return_value = []

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
        self.do_reconcile(requirements={"security": 1}, datasets=[])
        self.batch_v1.create_namespaced_job.assert_called_once()
        self.assertIsInstance(self.created_job(), client.V1Job)
        self.assertEqual(self.patched_phases(), [PENDING_PHASE, SCHEDULED_PHASE])

    def test_datasets_fetched_once_via_get_all_datasets(self):
        self.dataset_service.get_all_datasets.return_value = [
            {"requirements": {"security": 2}, "geo": None},
            {"requirements": {"computation": 3}, "geo": None},
        ]
        self.do_reconcile(datasets=["d1", "d2"])
        self.dataset_service.get_all_datasets.assert_called_once_with(["d1", "d2"])

    def test_full_reconcile_annotations_reflect_beta_star_and_datasets(self):
        self.dataset_service.get_all_datasets.return_value = [
            {"requirements": {"security": 2}, "geo": None},
            {"requirements": {"computation": 3}, "geo": None},
        ]
        self.do_reconcile(datasets=["d1", "d2"])
        self.assertEqual(
            json.loads(self.job_annotation(BETA_STAR_ANNOTATION_DEFAULT)),
            {"security": 2, "computation": 3},
        )
        self.assertEqual(
            json.loads(self.job_annotation(DATASETS_ANNOTATION_DEFAULT)), ["d1", "d2"]
        )

    def test_dataset_not_found_sets_failed_without_creating_job(self):
        self.dataset_service.get_all_datasets.side_effect = DatasetNotFoundError(
            "missing"
        )
        self.do_reconcile(datasets=["missing"])
        self.batch_v1.create_namespaced_job.assert_not_called()
        self.assertIn(FAILURE_PHASE, self.patched_phases())
        self.assertNotIn(SCHEDULED_PHASE, self.patched_phases())

    def test_dataset_service_error_raises_temporary(self):
        import kopf

        self.dataset_service.get_all_datasets.side_effect = DatasetServiceError(
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


class TestReconcileGeo(ControllerTestBase):
    """Tests for geo*(t) computation during reconciliation."""

    def test_geo_omega_creates_job_with_no_geo_annotation(self):
        self.do_reconcile(geo=None, datasets=[])
        self.assertIsNone(self.job_annotation(GEO_STAR_ANNOTATION_DEFAULT))
        self.assertEqual(self.patched_phases(), [PENDING_PHASE, SCHEDULED_PHASE])

    def test_geo_t_resolved_against_registry(self):
        self.load_geo_groups(("EU", ["eu-west", "eu-north"], []))
        self.do_reconcile(geo="EU", datasets=[])
        self.assertEqual(
            set(json.loads(self.job_annotation(GEO_STAR_ANNOTATION_DEFAULT))),
            {"eu-west", "eu-north"},
        )
        self.assertEqual(self.patched_phases(), [PENDING_PHASE, SCHEDULED_PHASE])

    def test_geo_intersection_with_dataset_geo(self):
        self.load_geo_groups(
            ("EU", ["eu-west", "eu-north"], []),
            ("OECD", [], ["EU", "US"]),
            ("US", ["us-west"], []),
        )
        self.dataset_service.get_all_datasets.return_value = [
            {"requirements": {}, "geo": "EU"},
        ]
        self.do_reconcile(geo="OECD", datasets=["d1"])
        # OECD intersection EU = EU
        self.assertEqual(
            set(json.loads(self.job_annotation(GEO_STAR_ANNOTATION_DEFAULT))),
            {"eu-west", "eu-north"},
        )

    def test_empty_intersection_sets_failed_without_creating_job(self):
        self.load_geo_groups(
            ("EU", ["eu-west"], []),
            ("US", ["us-west"], []),
        )
        self.dataset_service.get_all_datasets.return_value = [
            {"requirements": {}, "geo": "US"},
        ]
        self.do_reconcile(geo="EU", datasets=["d1"])
        self.batch_v1.create_namespaced_job.assert_not_called()
        self.assertIn(FAILURE_PHASE, self.patched_phases())
        self.assertNotIn(SCHEDULED_PHASE, self.patched_phases())
        self.assertIn("geo*(t)", self.last_failure_message())

    def test_unknown_geo_group_is_skipped_not_failed(self):
        # No groups registered at all: "EU" is unresolved and skipped,
        # resulting in Omega (no constraint), not a failure.
        self.do_reconcile(geo="EU", datasets=[])
        self.assertEqual(self.patched_phases(), [PENDING_PHASE, SCHEDULED_PHASE])
        self.assertIsNone(self.job_annotation(GEO_STAR_ANNOTATION_DEFAULT))

    def test_geo_group_deleted_no_longer_resolved(self):
        self.load_geo_groups(("EU", ["eu-west"], []))
        self.ctrl.on_geographical_group_deleted("EU", self.logger)
        self.do_reconcile(geo="EU", datasets=[])
        # EU no longer in registry: skipped -> Omega -> Job still created.
        self.assertEqual(self.patched_phases(), [PENDING_PHASE, SCHEDULED_PHASE])
        self.assertIsNone(self.job_annotation(GEO_STAR_ANNOTATION_DEFAULT))

    def test_geo_affinity_present_on_job(self):
        self.load_geo_groups(("EU", ["eu-west", "eu-north"], []))
        self.do_reconcile(geo="EU", datasets=[])
        job = self.created_job()
        terms = (
            job.spec.template.spec.affinity.node_affinity.required_during_scheduling_ignored_during_execution.node_selector_terms
        )
        exprs = [e for t in terms for e in (t.match_expressions or [])]
        geo_exprs = [e for e in exprs if e.key == self.cfg.node_topology_location_label]
        self.assertEqual(len(geo_exprs), 1)
        self.assertEqual(geo_exprs[0].operator, "In")
        self.assertEqual(set(geo_exprs[0].values), {"eu-west", "eu-north"})


class TestGeoGroupRegistry(ControllerTestBase):
    def test_created_group_added_to_registry(self):
        self.ctrl.on_geographical_group_created_or_updated(
            "EU", {"locations": ["eu-west"], "includes": []}, self.logger
        )
        self.assertIn("EU", self.ctrl._geo_groups)

    def test_updated_group_replaces_previous(self):
        self.ctrl.on_geographical_group_created_or_updated(
            "EU", {"locations": ["eu-west"], "includes": []}, self.logger
        )
        self.ctrl.on_geographical_group_created_or_updated(
            "EU", {"locations": ["eu-north"], "includes": []}, self.logger
        )
        self.assertEqual(self.ctrl._geo_groups["EU"].locations, ["eu-north"])

    def test_deleted_group_removed_from_registry(self):
        self.ctrl.on_geographical_group_created_or_updated(
            "EU", {"locations": ["eu-west"], "includes": []}, self.logger
        )
        self.ctrl.on_geographical_group_deleted("EU", self.logger)
        self.assertNotIn("EU", self.ctrl._geo_groups)

    def test_delete_nonexistent_does_not_raise(self):
        self.ctrl.on_geographical_group_deleted("NONEXISTENT", self.logger)

    def test_missing_locations_and_includes_default_to_empty(self):
        self.ctrl.on_geographical_group_created_or_updated("G", {}, self.logger)
        group = self.ctrl._geo_groups["G"]
        self.assertEqual(group.locations, [])
        self.assertEqual(group.includes, [])


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
