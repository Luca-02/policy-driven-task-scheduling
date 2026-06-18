import json
import unittest

from kubernetes import client

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
from src.job_builder import JobBuilder

NAME_DEFAULT = "test-name"
NAMESPACE_DEFAULT = "test-namespace"
OWNER_UID_DEFAULT = "test-uid"


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


class JobBuilderTestBase(unittest.TestCase):
    def setUp(self):
        self.cfg = make_config()
        self.builder = JobBuilder(config=self.cfg)

    def _full_builder(
        self,
        name=NAME_DEFAULT,
        namespace=NAMESPACE_DEFAULT,
        beta_star=None,
        geo_star=None,
        datasets=None,
        owner_uid=OWNER_UID_DEFAULT,
    ) -> JobBuilder:
        return (
            self.builder.set_name(name)
            .set_namespace(namespace)
            .set_beta_star(beta_star or {})
            .set_geo_star(geo_star)
            .set_datasets(datasets or [])
            .set_owner(owner_uid)
        )

    def _build(self, **kwargs) -> client.V1Job:
        return self._full_builder(**kwargs).build()

    def _match_expressions(
        self, job: client.V1Job
    ) -> list[client.V1NodeSelectorRequirement]:
        affinity: client.V1Affinity = job.spec.template.spec.affinity
        self.assertIsNotNone(affinity)
        terms = (
            affinity.node_affinity.required_during_scheduling_ignored_during_execution.node_selector_terms
        )
        return [expr for term in terms for expr in (term.match_expressions or [])]


class TestJobBuilderGeneral(JobBuilderTestBase):
    def test_returns_v1job(self):
        self.assertIsInstance(self._build(), client.V1Job)

    def test_metadata(self):
        job = self._build(name="my-task")
        self.assertEqual(job.metadata.name, "my-task")
        self.assertEqual(job.metadata.namespace, NAMESPACE_DEFAULT)

    def test_owner_reference(self):
        ref = self._build().metadata.owner_references[0]
        self.assertEqual(ref.kind, self.cfg.task_request_kind)
        self.assertEqual(ref.name, NAME_DEFAULT)
        self.assertEqual(ref.uid, OWNER_UID_DEFAULT)
        self.assertTrue(ref.controller)
        self.assertTrue(ref.block_owner_deletion)

    def test_task_request_label(self):
        name = "t1"
        key = f"{self.cfg.job_label_prefix}/{self.cfg.task_request_ref_label}"
        self.assertEqual(self._build(name=name).metadata.labels[key], name)

    def test_scheduling_annotations_present(self):
        beta_star = {"security": 2, "computation": 1}
        job = self._build(beta_star=beta_star, datasets=["d1"])
        annotations = job.metadata.annotations
        beta_key = f"{self.cfg.job_annotation_prefix}/{self.cfg.beta_star_annotation}"
        ds_key = f"{self.cfg.job_annotation_prefix}/{self.cfg.datasets_annotation}"
        self.assertEqual(json.loads(annotations[beta_key]), beta_star)
        self.assertEqual(json.loads(annotations[ds_key]), ["d1"])


class TestPropertyExpressions(JobBuilderTestBase):
    def test_single_property_generates_gt_expression(self):
        exprs = self._match_expressions(self._build(beta_star={"security": 2}))
        self.assertEqual(len(exprs), 1)
        self.assertEqual(exprs[0].key, f"{self.cfg.node_property_prefix}/security")
        self.assertEqual(exprs[0].operator, "Gt")
        self.assertEqual(exprs[0].values, ["1"])

    def test_gt_value_is_level_minus_one(self):
        for level in (1, 2, 3):
            with self.subTest(level=level):
                exprs = self._match_expressions(
                    self._build(beta_star={"security": level})
                )
                self.assertEqual(exprs[0].values, [str(level - 1)])

    def test_multiple_properties_all_present(self):
        keys = {
            e.key
            for e in self._match_expressions(
                self._build(beta_star={"security": 2, "computation": 3})
            )
        }
        self.assertIn(f"{self.cfg.node_property_prefix}/security", keys)
        self.assertIn(f"{self.cfg.node_property_prefix}/computation", keys)

    def test_level_zero_excluded_from_affinity(self):
        keys = {
            e.key
            for e in self._match_expressions(
                self._build(beta_star={"security": 0, "computation": 2})
            )
        }
        self.assertNotIn(f"{self.cfg.node_property_prefix}/security", keys)

    def test_affinity_uses_required_during_scheduling(self):
        na = self._build(
            beta_star={"security": 1}
        ).spec.template.spec.affinity.node_affinity
        self.assertIsNotNone(na.required_during_scheduling_ignored_during_execution)
        self.assertIsNone(na.preferred_during_scheduling_ignored_during_execution)

    def test_property_expressions_returns_v1_node_selector_requirements(self):
        self.builder.set_beta_star({"security": 2, "computation": 1})
        exprs = self.builder._property_expressions()
        self.assertTrue(
            all(isinstance(e, client.V1NodeSelectorRequirement) for e in exprs)
        )
        self.assertEqual(len(exprs), 2)

    def test_property_expressions_empty_when_all_zero(self):
        self.builder.set_beta_star({"security": 0})
        self.assertEqual(self.builder._property_expressions(), [])


class TestGeoExpressions(JobBuilderTestBase):
    def test_geo_none_produces_no_geo_expression(self):
        self.builder.set_beta_star({"security": 1})
        self.builder.set_geo_star(None)
        self.assertEqual(self.builder._geo_expressions(), [])

    def test_geo_set_generates_in_expression(self):
        self.builder.set_geo_star({"eu-west", "eu-north"})
        exprs = self.builder._geo_expressions()
        self.assertEqual(len(exprs), 1)
        self.assertEqual(exprs[0].key, self.cfg.node_topology_location_label)
        self.assertEqual(exprs[0].operator, "In")
        self.assertEqual(set(exprs[0].values), {"eu-west", "eu-north"})

    def test_geo_none_and_no_properties_means_no_affinity(self):
        job = self._build(beta_star={}, geo_star=None)
        self.assertIsNone(job.spec.template.spec.affinity)

    def test_geo_alone_produces_affinity(self):
        job = self._build(beta_star={}, geo_star={"eu-west"})
        exprs = self._match_expressions(job)
        self.assertEqual(len(exprs), 1)
        self.assertEqual(exprs[0].key, self.cfg.node_topology_location_label)

    def test_geo_and_property_both_present_in_affinity(self):
        job = self._build(beta_star={"security": 1}, geo_star={"eu-west"})
        keys = {e.key for e in self._match_expressions(job)}
        self.assertIn(f"{self.cfg.node_property_prefix}/security", keys)
        self.assertIn(self.cfg.node_topology_location_label, keys)

    def test_geo_star_annotation_present_when_geo_set(self):
        job = self._build(geo_star={"eu-west", "eu-north"})
        key = f"{self.cfg.job_annotation_prefix}/{self.cfg.geo_star_annotation}"
        self.assertEqual(
            json.loads(job.metadata.annotations[key]), sorted(["eu-west", "eu-north"])
        )

    def test_geo_star_annotation_absent_when_geo_none(self):
        job = self._build(geo_star=None)
        key = f"{self.cfg.job_annotation_prefix}/{self.cfg.geo_star_annotation}"
        self.assertNotIn(key, job.metadata.annotations)


class TestAllZeroOrOmegaProducesNoAffinity(JobBuilderTestBase):
    def test_all_zero_beta_and_omega_geo_produces_no_affinity(self):
        for beta_star in ({}, {"security": 0}):
            with self.subTest(beta_star=beta_star):
                job = self._build(beta_star=beta_star, geo_star=None)
                self.assertIsNone(job.spec.template.spec.affinity)
