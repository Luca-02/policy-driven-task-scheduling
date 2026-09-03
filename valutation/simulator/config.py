"""Parameter schema for a simulation run.

A ``SimConfig`` fully determines a run together with a seed: same config and
same seed produce the same cluster, the same conflict set and the same batch.

Every field here must be expressible as a Kubernetes manifest (NodeProperty,
GeographicalGroup, dataset seed, TaskRequest) so that the same configuration
can drive both the simulator and the prototype. Do not add parameters that
have no counterpart in the deployed system.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum

from model import UNLIMITED


class Template(str, Enum):
    """How property classes are distributed across the cluster template.

    FLAT:        every node offers the maximum level of every property.
                 Admissibility is never restricted by c_prop, but tasks run
                 with the largest possible privilege excess.
    STRATIFIED:  classes drawn uniformly over the whole property lattice.
                 Minimises excess, restricts the candidate pool.
    REALISTIC:   skewed towards low levels, few high-end nodes.
    """

    FLAT = "flat"
    STRATIFIED = "stratified"
    REALISTIC = "realistic"


class SanitizationStrategy(str, Enum):
    """When sanitization is triggered.

    Only PERIODIC is implemented in the prototype. THRESHOLD is described in
    the model as a possible refinement and is evaluated here for comparison.

    NONE:      never sanitize; yields the asymptotic starvation rate, the
               upper bound against which every other strategy is read.
    PERIODIC:  every ``period`` steps, all nodes with a non-empty footprint.
    THRESHOLD: nodes whose footprint reaches ``threshold`` contexts.
    """

    NONE = "none"
    PERIODIC = "periodic"
    THRESHOLD = "threshold"


@dataclass
class PropertyConfig:
    """Abstract node properties and their number of levels.

    Mirrors the NodeProperty resources of the prototype. Three properties,
    three levels each: two mirror the prototype's examples (computation,
    security), the third (network) represents the node's network assurance
    tier, relevant here because the thesis's whole subject is protecting
    data in transit between nodes.
    """

    max_levels: dict[str, int] = field(
        default_factory=lambda: {"computation": 3, "security": 3, "network": 3}
    )

    @property
    def names(self) -> list[str]:
        return sorted(self.max_levels)


@dataclass
class GeoConfig:
    """Geographical hierarchy.

    Generates ``n_regions`` groups of ``locations_per_region`` locations each,
    plus one umbrella group including them all, matching the eu / us / oecd
    shape used in the prototype examples.
    """

    n_regions: int = 2
    locations_per_region: int = 4
    umbrella_name: str = "global"
    region_prefix: str = "r"


@dataclass
class ClusterConfig:
    """Cluster composition and size.

    ``template_size`` fixes the composition, ``replication_factor`` scales it:
    the cluster is ``replication_factor`` copies of the same template, so size
    varies while the proportions of classes and locations stay fixed. This is
    what makes an effect attributable to scale rather than to composition.

    ``template_size`` is coupled to the property lattice: with 3 properties at
    3 levels each there are 3^3 = 27 possible classes, and 36 keeps the same
    ~1.33 ratio used when the model had 2 properties (12 nodes over a 9-class
    lattice), giving the STRATIFIED template full coverage of the lattice
    with mild redundancy rather than a sparse sample of it. Adding another
    property means revisiting this value again, not just ``max_levels``.
    """

    template: Template = Template.REALISTIC
    template_size: int = 36
    replication_factor: int = 1

    # Simulator-only: concurrent tasks per node. UNLIMITED disables contention.
    slots_per_node: int = UNLIMITED

    @property
    def n_nodes(self) -> int:
        return self.template_size * self.replication_factor


@dataclass
class DatasetConfig:
    """Dataset population.

    ``placement_replication`` is how many template nodes hold each dataset.
    For a static dataset this is a hard placement constraint (c_static); for a
    non-static one it only determines locality, and therefore phi_transfer.

    ``replicate_placement`` decides whether dataset placement is propagated to
    the cluster replicas produced by ``replication_factor``. Setting it to
    False is what exposes the interaction between horizontal node redundancy
    and static datasets: adding nodes does not help tasks pinned to where the
    data already is.

    ``beta_weights`` gives the relative frequency of each requirement level,
    from 0 upwards, for every property of a dataset. Weights rather than a
    hard ceiling, because beta*(t) is a least upper bound over every property
    of every requested dataset: with three properties and up to three
    datasets it aggregates up to nine independent draws, so even a small
    per-draw probability of the top level becomes common at task level. A
    ceiling would leave the top level either impossible or typical, with
    nothing in between; weights place it where it belongs, as an exception.
    """

    n_datasets: int = 40
    static_fraction: float = 0.25
    placement_replication: int = 3
    replicate_placement: bool = True
    beta_weights: list[float] = field(default_factory=lambda: [20, 20, 12, 1])
    size_min: float = 128.0
    size_max: float = 4096.0
    # Probability that a dataset carries no context at all (public data).
    public_fraction: float = 0.1
    # Probability that geo(d) is the umbrella group rather than a single
    # region. Kept high by default: since geo*(t) is an intersection, drawing
    # regions independently would make it empty most of the time and
    # translation-time rejections would mask every other effect.
    geo_umbrella_fraction: float = 0.85


@dataclass
class ContextConfig:
    """Contexts, issuers and the conflict graph.

    ``conflict_density`` is the fraction of the C(n_contexts, 2) possible
    pairs that belong to X_conf. A density rather than an absolute count, so
    that results stay comparable when the number of contexts changes.
    """

    n_contexts: int = 30
    conflict_density: float = 0.1
    auth_size: int = 1


@dataclass
class WorkloadConfig:
    """The batch of submitted tasks.

    ``beta_weights`` is skewed lower than the dataset one on purpose: the
    issuer asks for little, and beta*(t) is pushed up mainly by the data the
    task consumes. That asymmetry is what makes the amplification predicted
    by the model visible, rather than an artefact of demanding tasks.
    """

    n_tasks: int = 3000
    req_min: int = 1
    req_max: int = 3
    beta_weights: list[float] = field(default_factory=lambda: [30, 20, 5, 1])
    # Simulator-only: how many steps a task occupies a slot.
    duration: int = 10
    # Fraction of tasks that carry an explicit geo(t) instead of None.
    geo_fraction: float = 0.5


@dataclass
class SanitizationConfig:
    strategy: SanitizationStrategy = SanitizationStrategy.PERIODIC
    period: int = 50  # PERIODIC only
    threshold: int = 3  # THRESHOLD only


@dataclass
class ScoringConfig:
    """Weights of the optimisation indicators."""

    w_prop: float = 1.0
    w_transfer: float = 2.0
    # Per-property weights for the excess Delta; defaults to 1 for each.
    prop_weights: dict[str, float] = field(default_factory=dict)


@dataclass
class SimConfig:
    """A complete, reproducible simulation configuration."""

    properties: PropertyConfig = field(default_factory=PropertyConfig)
    geo: GeoConfig = field(default_factory=GeoConfig)
    cluster: ClusterConfig = field(default_factory=ClusterConfig)
    datasets: DatasetConfig = field(default_factory=DatasetConfig)
    contexts: ContextConfig = field(default_factory=ContextConfig)
    workload: WorkloadConfig = field(default_factory=WorkloadConfig)
    sanitization: SanitizationConfig = field(default_factory=SanitizationConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    seed: int = 0

    # -- serialisation -----------------------------------------------------

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True, default=str)

    @staticmethod
    def from_dict(data: dict) -> "SimConfig":
        return SimConfig(
            properties=PropertyConfig(**data.get("properties", {})),
            geo=GeoConfig(**data.get("geo", {})),
            cluster=ClusterConfig(
                **(
                    {
                        **data.get("cluster", {}),
                        "template": Template(data["cluster"]["template"]),
                    }
                    if "cluster" in data
                    else {}
                )
            ),
            datasets=DatasetConfig(**data.get("datasets", {})),
            contexts=ContextConfig(**data.get("contexts", {})),
            workload=WorkloadConfig(**data.get("workload", {})),
            sanitization=SanitizationConfig(
                **(
                    {
                        **data.get("sanitization", {}),
                        "strategy": SanitizationStrategy(
                            data["sanitization"]["strategy"]
                        ),
                    }
                    if "sanitization" in data
                    else {}
                )
            ),
            scoring=ScoringConfig(**data.get("scoring", {})),
            seed=data.get("seed", 0),
        )

    @staticmethod
    def from_json(text: str) -> "SimConfig":
        return SimConfig.from_dict(json.loads(text))

    # -- convenience -------------------------------------------------------

    def replace(self, **overrides) -> "SimConfig":
        """Return a copy with dotted overrides applied.

        Sweeps are expressed as small deviations from a baseline, so this
        keeps grid definitions readable:

            base.replace(**{"contexts.conflict_density": 0.2, "seed": 3})
        """
        import copy

        out = copy.deepcopy(self)
        for path, value in overrides.items():
            target = out
            parts = path.split(".")
            for part in parts[:-1]:
                target = getattr(target, part)
            setattr(target, parts[-1], value)
        return out

    def flat_params(self) -> dict:
        """Flatten the config into scalar columns for CSV output."""
        flat: dict = {}

        def walk(prefix: str, obj) -> None:
            for key, value in asdict(obj).items():
                name = f"{prefix}{key}"
                if isinstance(value, (dict, list)):
                    flat[name] = json.dumps(value, sort_keys=True)
                elif isinstance(value, Enum):
                    flat[name] = value.value
                else:
                    flat[name] = value

        for section in (
            "properties",
            "geo",
            "cluster",
            "datasets",
            "contexts",
            "workload",
            "sanitization",
            "scoring",
        ):
            walk(f"{section}.", getattr(self, section))
        flat["seed"] = self.seed
        flat["cluster.n_nodes"] = self.cluster.n_nodes
        return flat


# A baseline configuration the sweeps deviate from.
BASELINE = SimConfig()
