import json

from kubernetes import client

from src.config import Config


class JobBuilder:
    """
    Builder for a typed V1Job manifest representing a scheduled TaskRequest.

    Setting the UID of the TaskRequest as an owner reference on the Job ensures
    that the Job is automatically garbage collected when the TaskRequest is deleted.

    The resulting Job carries:
    - A label linking it back to the originating TaskRequest.
    - A datasets annotation with the serialised list of required dataset names.
    - A beta-star annotation with the serialised `beta*(t)`.
    - A geo-star annotation with the serialised `geo*(t)` (omitted if None -> `Omega`).
    - A nodeAffinity realising filter steps `c_prop`.
    - A nodeAffinity realising filter steps `c_geo`.
    - A nodeAffinity realising filter steps `c_static`.
    """

    def __init__(self, config: Config):
        self._config = config
        self._name: str | None = None
        self._namespace: str | None = None
        self._beta_star: dict[str, int] = {}
        self._geo_star: set[str] | None = None
        self._datasets: set[str] = set()
        self._static_nodes: set[str] | None = None
        self._owner_uid: str | None = None

    def set_name(self, name: str) -> "JobBuilder":
        self._name = name
        return self

    def set_namespace(self, namespace: str) -> "JobBuilder":
        self._namespace = namespace
        return self

    def set_beta_star(self, beta_star: dict[str, int]) -> "JobBuilder":
        self._beta_star = beta_star
        return self

    def set_geo_star(self, geo_star: set[str] | None) -> "JobBuilder":
        self._geo_star = geo_star
        return self

    def set_datasets(self, datasets: set[str]) -> "JobBuilder":
        self._datasets = datasets
        return self

    def set_static_nodes(self, static_nodes: set[str] | None) -> "JobBuilder":
        self._static_nodes = static_nodes
        return self

    def set_owner(self, owner_uid: str) -> "JobBuilder":
        self._owner_uid = owner_uid
        return self

    def build(self) -> client.V1Job:
        """
        Assemble and return the V1Job.

        Returns:
            client.V1Job: The V1Job object ready to be created in the cluster.
        """
        return client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=self._build_metadata(),
            spec=self._build_spec(),
        )

    def _scheduling_annotations(self) -> dict:
        """
        Build the scheduling annotations.

        Returns:
            dict: A dictionary of annotations for the Job's pod template.
        """
        datasets_key = (
            f"{self._config.job_annotation_prefix}/{self._config.datasets_annotation}"
        )
        beta_star_key = (
            f"{self._config.job_annotation_prefix}/{self._config.beta_star_annotation}"
        )
        geo_star_key = (
            f"{self._config.job_annotation_prefix}/{self._config.geo_star_annotation}"
        )

        annotations = {}
        for key, value in (
            (datasets_key, sorted(self._datasets) if self._datasets else None),
            (beta_star_key, self._beta_star),
            (geo_star_key, sorted(self._geo_star) if self._geo_star else None),
        ):
            if value:
                annotations[key] = json.dumps(value)
        return annotations

    def _build_metadata(self) -> client.V1ObjectMeta:
        """
        Build the metadata for the Job, including labels and owner references.

        Returns:
            client.V1ObjectMeta: The metadata object for the Job.
        """
        labels = {
            f"{self._config.job_label_prefix}/{self._config.task_request_ref_label}": self._name
        }

        owner_references = []
        if self._name and self._owner_uid:
            owner_references = [
                client.V1OwnerReference(
                    api_version=f"{self._config.group}/{self._config.version}",
                    kind=self._config.task_request_kind,
                    name=self._name,
                    uid=self._owner_uid,
                    controller=True,
                    block_owner_deletion=True,
                )
            ]

        return client.V1ObjectMeta(
            name=self._name,
            namespace=self._namespace,
            labels=labels,
            owner_references=owner_references,
        )

    def _build_spec(self) -> client.V1JobSpec:
        """
        Build the spec for the Job, including the pod template with the
        appropriate affinity and pod annotations.
        """
        return client.V1JobSpec(
            backoff_limit=0,
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(
                    annotations=self._scheduling_annotations(),
                ),
                spec=client.V1PodSpec(
                    restart_policy="Never",
                    affinity=self._build_affinity(),
                    scheduler_name=self._config.scheduler_name,
                    containers=self._build_containers()
                ),
            ),
        )
    
    def _build_containers(self) -> list[client.V1Container]:
        """
        Build the list of containers for the Job's pod template.

        **Blackbox image placeholder**: in a real implementation the task
        image would be supplied as metadata in the TaskRequest spec and
        validated by a dedicated `image-service` before the controller
        translates the request into a Job.

        Returns:
            list[client.V1Container]: A list containing a single container for the Job.
        """
        return [
            client.V1Container(
                name="task",
                image="busybox:latest",
                command=[
                    "sh",
                    "-c",
                    'echo "Task executed successfully" && sleep 5',
                ],
            )
        ]

    def _build_affinity(self) -> client.V1Affinity | None:
        """
        Assemble nodeAffinity from all scheduling policies match expressions.

        Returns:
            client.V1Affinity: The affinity object for the Job, or None if no
                match expressions are generated.
        """
        match_expressions = [
            *self._property_expressions(),
            *self._geo_expressions(),
            *self._static_expressions(),
        ]

        if not match_expressions:
            return None

        return client.V1Affinity(
            node_affinity=client.V1NodeAffinity(
                required_during_scheduling_ignored_during_execution=client.V1NodeSelector(
                    node_selector_terms=[
                        client.V1NodeSelectorTerm(match_expressions=match_expressions)
                    ]
                )
            )
        )

    def _property_expressions(self) -> list[client.V1NodeSelectorRequirement]:
        """
        Translate `beta*(t)` into match expressions realising the filter step `c_prop`.

        For each property p with a level `beta*(t)[p] > 0`, the node property label must satisfy
        operator Gt with value `beta*(t)[p] - 1`, equivalent to `alpha(n)[p] ≥ beta*(t)[p]`
        given that labels carry integer values.

        Properties with level 0 are excluded as level 0 is the implicit default in the formal model.

        Returns:
            list[client.V1NodeSelectorRequirement]: A list of match expressions for the node selector
        """
        return [
            client.V1NodeSelectorRequirement(
                key=f"{self._config.node_property_prefix}/{prop}",
                operator="Gt",
                values=[str(level - 1)],
            )
            for prop, level in self._beta_star.items()
            if level > 0
        ]

    def _geo_expressions(self) -> list[client.V1NodeSelectorRequirement]:
        """
        Translate `geo*(t)` into a match expression realising the filter step `c_geo`.

        Returns:
            list[client.V1NodeSelectorRequirement]: A list of a single match expression for the node selector,
                or an empty list if `geo*(t)` is None (i.e., `Omega`).
        """
        if self._geo_star is None:
            return []

        return [
            client.V1NodeSelectorRequirement(
                key=self._config.node_topology_location_label,
                operator="In",
                values=sorted(self._geo_star),
            )
        ]

    def _static_expressions(self) -> list[client.V1NodeSelectorRequirement]:
        """
        Translate the intersection of static datasets related nodes into a match
        expression realising the filter step `c_static`.

        Returns:
            list[client.V1NodeSelectorRequirement]: A list of a single match expression for the node selector,
                or an empty list if there are no static datasets (no constraint).
        """
        if self._static_nodes is None:
            return []

        return [
            client.V1NodeSelectorRequirement(
                key="kubernetes.io/hostname",
                operator="In",
                values=sorted(self._static_nodes),
            )
        ]
