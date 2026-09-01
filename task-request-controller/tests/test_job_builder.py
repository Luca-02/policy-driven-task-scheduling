import json
import unittest

from kubernetes import client

from tests.test_config_base import make_config
from src.job_builder import JobBuilder

NAME_DEFAULT = "test-name"
NAMESPACE_DEFAULT = "test-namespace"
OWNER_UID_DEFAULT = "test-uid"
ISSUER_DEFAULT = "alice"


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
        ctx_star=None,
        datasets=None,
        static_nodes=None,
        owner_uid=OWNER_UID_DEFAULT,
        issuer=ISSUER_DEFAULT,
    ) -> JobBuilder:
        return (
            self.builder.set_name(name)
            .set_namespace(namespace)
            .set_owner(owner_uid)
            .set_issuer(issuer)
            .set_datasets(datasets or set())
            .set_beta_star(beta_star or dict())
            .set_geo_star(geo_star)
            .set_ctx_star(ctx_star or set())
            .set_static_nodes(static_nodes)
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
        annotations = job.spec.template.metadata.annotations
        beta_key = f"{self.cfg.job_annotation_prefix}/{self.cfg.beta_star_annotation}"
        ds_key = f"{self.cfg.job_annotation_prefix}/{self.cfg.datasets_annotation}"
        self.assertEqual(json.loads(annotations[beta_key]), beta_star)
        self.assertEqual(json.loads(annotations[ds_key]), ["d1"])

    def test_pod_uses_configured_scheduler(self):
        job = self._build()
        self.assertEqual(job.spec.template.spec.scheduler_name, self.cfg.scheduler_name)

    def test_task_container_uses_configured_simulated_duration(self):
        self.cfg.task_simulated_duration_seconds = 42
        container = self._build().spec.template.spec.containers[0]
        env = {e.name: e.value for e in container.env}
        self.assertEqual(env["TASK_SIMULATED_DURATION_SECONDS"], "42")
        self.assertIn('sleep "$TASK_SIMULATED_DURATION_SECONDS"', container.command[-1])

    def test_all_zero_beta_and_omega_geo_produces_no_affinity(self):
        for beta_star in ({}, {"security": 0}):
            with self.subTest(beta_star=beta_star):
                job = self._build(beta_star=beta_star, geo_star=None)
                self.assertIsNone(job.spec.template.spec.affinity)


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
            json.loads(job.spec.template.metadata.annotations[key]),
            sorted(["eu-west", "eu-north"]),
        )

    def test_geo_star_annotation_absent_when_geo_none(self):
        job = self._build(geo_star=None)
        key = f"{self.cfg.job_annotation_prefix}/{self.cfg.geo_star_annotation}"
        self.assertNotIn(key, job.spec.template.metadata.annotations)


class TestCtxStarAnnotation(JobBuilderTestBase):
    def test_ctx_star_annotation_present_when_ctx_set(self):
        job = self._build(ctx_star={"ford", "ferrari"})
        key = f"{self.cfg.job_annotation_prefix}/{self.cfg.ctx_star_annotation}"
        self.assertEqual(
            json.loads(job.spec.template.metadata.annotations[key]),
            sorted(["ford", "ferrari"]),
        )

    def test_ctx_star_annotation_absent_when_empty(self):
        job = self._build(ctx_star=set())
        key = f"{self.cfg.job_annotation_prefix}/{self.cfg.ctx_star_annotation}"
        self.assertNotIn(key, job.spec.template.metadata.annotations)

    def test_ctx_star_does_not_affect_affinity(self):
        job = self._build(beta_star={}, geo_star=None, ctx_star={"ford"})
        self.assertIsNone(job.spec.template.spec.affinity)


class TestStaticExpressions(JobBuilderTestBase):
    def test_static_nodes_none_produces_no_expression(self):
        self.builder.set_beta_star({"security": 1})
        self.builder.set_static_nodes(None)
        self.assertEqual(self.builder._static_expressions(), [])

    def test_static_nodes_set_generates_in_expression(self):
        self.builder.set_static_nodes({"n1", "n2"})
        exprs = self.builder._static_expressions()
        self.assertEqual(len(exprs), 1)
        self.assertEqual(exprs[0].key, "kubernetes.io/hostname")
        self.assertEqual(exprs[0].operator, "In")
        self.assertEqual(set(exprs[0].values), {"n1", "n2"})

    def test_static_nodes_values_are_sorted(self):
        self.builder.set_static_nodes({"n3", "n1", "n2"})
        exprs = self.builder._static_expressions()
        self.assertEqual(exprs[0].values, ["n1", "n2", "n3"])

    def test_static_none_and_no_properties_means_no_affinity(self):
        job = self._build(beta_star={}, static_nodes=None)
        self.assertIsNone(job.spec.template.spec.affinity)

    def test_static_alone_produces_affinity(self):
        job = self._build(beta_star={}, static_nodes={"n1"})
        exprs = self._match_expressions(job)
        self.assertEqual(len(exprs), 1)
        self.assertEqual(exprs[0].key, "kubernetes.io/hostname")

    def test_static_and_property_both_present_in_affinity(self):
        job = self._build(beta_star={"security": 1}, static_nodes={"n1"})
        keys = {e.key for e in self._match_expressions(job)}
        self.assertIn(f"{self.cfg.node_property_prefix}/security", keys)
        self.assertIn("kubernetes.io/hostname", keys)

    def test_static_and_geo_both_present_same_term(self):
        job = self._build(geo_star={"eu-west"}, static_nodes={"n1"})
        terms = (
            job.spec.template.spec.affinity.node_affinity.required_during_scheduling_ignored_during_execution.node_selector_terms
        )
        self.assertEqual(len(terms), 1)
        keys = {e.key for e in self._match_expressions(job)}
        self.assertIn(self.cfg.node_topology_location_label, keys)
        self.assertIn("kubernetes.io/hostname", keys)


class TestPodTemplateAnnotations(JobBuilderTestBase):
    def _pod_annotations(self, job: client.V1Job) -> dict:
        meta = job.spec.template.metadata
        self.assertIsNotNone(meta)
        return meta.annotations or {}

    def test_annotations_inherited_by_pod_template(self):
        # Le stesse annotazioni devono stare su Job E su Pod template.
        job = self._build(
            beta_star={"security": 2}, datasets=["d1"], geo_star={"eu-west"}
        )
        self.assertEqual(
            self._pod_annotations(job), job.spec.template.metadata.annotations
        )

    def test_beta_star_on_pod_template(self):
        job = self._build(beta_star={"security": 2}, datasets=["d1"])
        key = f"{self.cfg.job_annotation_prefix}/{self.cfg.beta_star_annotation}"
        self.assertEqual(json.loads(self._pod_annotations(job)[key]), {"security": 2})

    def test_ctx_star_on_pod_template(self):
        job = self._build(ctx_star={"ford"})
        key = f"{self.cfg.job_annotation_prefix}/{self.cfg.ctx_star_annotation}"
        self.assertEqual(json.loads(self._pod_annotations(job)[key]), ["ford"])

    def test_datasets_on_pod_template_sorted(self):
        job = self._build(datasets=["d2", "d1"])
        key = f"{self.cfg.job_annotation_prefix}/{self.cfg.datasets_annotation}"
        self.assertEqual(json.loads(self._pod_annotations(job)[key]), ["d1", "d2"])

    def test_no_scheduling_data_empty_pod_annotations(self):
        job = self._build(beta_star={}, geo_star=None, datasets=[], issuer=None)
        self.assertEqual(self._pod_annotations(job), {})

    def test_issuer_on_pod_template(self):
        job = self._build(issuer=ISSUER_DEFAULT)
        key = f"{self.cfg.job_annotation_prefix}/{self.cfg.issuer_annotation}"
        self.assertEqual(self._pod_annotations(job)[key], ISSUER_DEFAULT)

    def test_issuer_annotation_absent_when_empty(self):
        job = self._build(issuer="")
        key = f"{self.cfg.job_annotation_prefix}/{self.cfg.issuer_annotation}"
        self.assertNotIn(key, self._pod_annotations(job))

    def test_issuer_annotation_absent_when_none(self):
        job = self._build(issuer=None)
        key = f"{self.cfg.job_annotation_prefix}/{self.cfg.issuer_annotation}"
        self.assertNotIn(key, self._pod_annotations(job))
