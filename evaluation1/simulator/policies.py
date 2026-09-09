"""Reference implementation of the formal model.

Every function here corresponds to a definition of Chapter 3 and nothing
else: no clock, no occupancy, no sanitization. Those belong to the simulation
machinery and live elsewhere, so that what is a property of the model and what
is an artefact of the simulator stays visible in the code.

All functions are pure. The only exception is the tie-break in ``select``,
which draws from a caller-supplied random stream so that runs stay
reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import random

from model import Cause, Dataset, GeoGroup, Node, Properties, ConflictSet

# ---------------------------------------------------------------------------
# Geographical groups
# ---------------------------------------------------------------------------


def resolve_geo(name: str, groups: dict[str, GeoGroup]) -> set[str]:
    """Flatten a geographical group into its set of locations.

    A group is either a set of locations or the union of other groups, so
    resolution is recursive. A name with no matching group is treated as a
    bare location, which is what allows geo(t) to name a single site. Cycles
    are guarded against rather than trusted not to occur.
    """
    seen: set[str] = set()

    def walk(current: str) -> set[str]:
        if current in seen:
            return set()
        seen.add(current)
        group = groups.get(current)
        if group is None:
            return {current}
        out = set(group.locations)
        for child in group.includes:
            out |= walk(child)
        return out

    return walk(name)


# ---------------------------------------------------------------------------
# Translation: effective requirements
# ---------------------------------------------------------------------------


def effective_beta(
    task_props: Properties,
    datasets: list[Dataset],
    max_levels: Properties,
) -> Properties:
    """beta*(t): the least upper bound of the task and dataset requirements.

    The effective requirement is not chosen by the issuer alone: any dataset
    demanding a higher level raises it. This is what makes the per-dataset
    policy redundant once beta*(t) is enforced.
    """
    beta: Properties = {p: task_props.get(p, 0) for p in max_levels}
    for dataset in datasets:
        for prop, level in dataset.props.items():
            if prop in beta:
                beta[prop] = max(beta[prop], level)
    return beta


def effective_geo(
    task_geo: str | None,
    datasets: list[Dataset],
    groups: dict[str, GeoGroup],
) -> set[str] | None:
    """geo*(t): the intersection of the task and dataset jurisdictions.

    Returns ``None`` when neither the task nor any dataset constrains the
    location, meaning c_geo admits every node. An empty set is a genuine
    rejection: the requested datasets are subject to jurisdictions with no
    common ground, so the task cannot run anywhere.
    """
    constraints: list[set[str]] = []
    if task_geo is not None:
        constraints.append(resolve_geo(task_geo, groups))
    for dataset in datasets:
        if dataset.geo is not None:
            constraints.append(resolve_geo(dataset.geo, groups))

    if not constraints:
        return None

    out = set(constraints[0])
    for other in constraints[1:]:
        out &= other
    return out


def ctx_star(datasets: list[Dataset]) -> set[str]:
    """ctx*(t): the union of the contexts of the requested datasets.

    This is what a task deposits on the node it runs on. It is empty when the
    task only uses public data, in which case nothing is deposited.
    """
    out: set[str] = set()
    for dataset in datasets:
        out |= dataset.contexts
    return out


def static_nodes(datasets: list[Dataset]) -> set[str] | None:
    """The intersection of lambda(d) over the requested static datasets.

    Returns ``None`` when no requested dataset is static, meaning c_static
    admits every node. An empty set is a rejection: no single node hosts all
    the required static data locally.
    """
    statics = [d for d in datasets if d.is_static]
    if not statics:
        return None

    out = set(statics[0].local_nodes)
    for dataset in statics[1:]:
        out &= dataset.local_nodes
    return out


@dataclass
class Translation:
    """Outcome of the translation phase."""

    beta_star: Properties = field(default_factory=dict)
    geo_star: set[str] | None = None
    ctx: set[str] = field(default_factory=set)
    static: set[str] | None = None
    cause: Cause = Cause.NONE

    @property
    def rejected(self) -> bool:
        return self.cause is not Cause.NONE


def translate(
    task_props: Properties,
    task_geo: str | None,
    datasets: list[Dataset],
    groups: dict[str, GeoGroup],
    max_levels: Properties,
    issuer_auth: set[str] | None = None,
) -> Translation:
    """Run the whole translation phase, stopping at the first rejection.

    The order follows the prototype: authorisation is checked at admission,
    then the effective requirements are computed and the two combinatorial
    rejections are raised before any node is inspected.
    """
    if issuer_auth is not None:
        for dataset in datasets:
            if not dataset.contexts <= issuer_auth:
                return Translation(cause=Cause.AUTH)

    beta = effective_beta(task_props, datasets, max_levels)

    geo = effective_geo(task_geo, datasets, groups)
    if geo is not None and not geo:
        return Translation(beta_star=beta, cause=Cause.GEO_EMPTY)

    contexts = ctx_star(datasets)

    static = static_nodes(datasets)
    if static is not None and not static:
        return Translation(
            beta_star=beta, geo_star=geo, ctx=contexts, cause=Cause.STATIC_EMPTY
        )

    return Translation(beta_star=beta, geo_star=geo, ctx=contexts, static=static)


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

# Policies are evaluated in this order, and a node is attributed to the first
# one it fails. Fixing the order is what makes the funnel cumulative and
# therefore readable: the count after each policy is the number of nodes that
# survived it and everything before it.
#
# Configuration-dependent policies come first, state-dependent ones after, so
# that the count after c_static is the pool a clean, idle cluster would offer.
# Anything lost beyond that point is due to accumulated state alone.
FILTER_ORDER: tuple[Cause, ...] = (
    Cause.PROP,
    Cause.GEO,
    Cause.STATIC,
    Cause.SANITIZING,
    Cause.WALL,
    Cause.CAPACITY,
)


@dataclass
class FilterOutcome:
    """Which nodes survived, and why the others did not."""

    admissible: list[Node] = field(default_factory=list)
    causes: dict[str, Cause] = field(default_factory=dict)
    funnel: dict[Cause, int] = field(default_factory=dict)
    n_nodes: int = 0

    @property
    def n_admissible(self) -> int:
        return len(self.admissible)

    def surviving_after(self, cause: Cause) -> int:
        return self.funnel.get(cause, 0)

    @property
    def n_after_static_policies(self) -> int:
        """Nodes surviving everything except the two stateful constraints.

        A task with none of these left would be rejected on a clean, idle
        cluster too, so this is what separates a rejection caused by the
        cluster configuration from one caused by the accumulated state.
        """
        return self.funnel.get(Cause.STATIC, 0)

    def exhausting_cause(self) -> Cause:
        """The policy after which no candidate is left.

        When a task ends up with an empty admissible set, several policies
        have usually excluded nodes; the one worth reporting is the first that
        brings the pool to zero, since it is the binding constraint. Returns
        NONE if the task is schedulable.
        """
        if self.admissible:
            return Cause.NONE
        for cause in FILTER_ORDER:
            if self.funnel.get(cause, 0) == 0:
                return cause
        return Cause.NONE


def dominates(props: Properties, required: Properties) -> bool:
    """alpha(n) >= beta*(t), component-wise over every property."""
    return all(props.get(prop, 0) >= level for prop, level in required.items())


def node_cause(
    node: Node,
    beta_star: Properties,
    geo_star: set[str] | None,
    static: set[str] | None,
    issuer_auth: set[str],
    conflicts: ConflictSet,
    check_state: bool = True,
) -> Cause:
    """The first policy the node fails, or NONE if it is admissible.

    ``check_state`` disables the two simulator-only constraints, which is how
    the stateless driver evaluates the solution space on a clean cluster.

    c_wall is tested against the issuer's whole authorisation perimeter
    auth(i), not against the contexts this particular task happens to use: the
    subject of the conflict of interest is the issuer, so a node carrying a
    trace conflicting with anything the issuer may access is barred.
    """
    if not dominates(node.props, beta_star):
        return Cause.PROP

    if geo_star is not None and node.loc not in geo_star:
        return Cause.GEO

    if static is not None and node.name not in static:
        return Cause.STATIC

    if check_state and node.sanitizing:
        return Cause.SANITIZING

    if node.lambda_ctx and conflicts.any_conflict(issuer_auth, node.lambda_ctx):
        return Cause.WALL

    if check_state and not node.has_free_slot():
        return Cause.CAPACITY

    return Cause.NONE


def filter_nodes(
    nodes: list[Node],
    beta_star: Properties,
    geo_star: set[str] | None,
    static: set[str] | None,
    issuer_auth: set[str],
    conflicts: ConflictSet,
    check_state: bool = True,
) -> FilterOutcome:
    """Evaluate every policy on every node and build the cumulative funnel."""
    outcome = FilterOutcome(n_nodes=len(nodes))
    counts: dict[Cause, int] = {cause: 0 for cause in FILTER_ORDER}

    for node in nodes:
        cause = node_cause(
            node, beta_star, geo_star, static, issuer_auth, conflicts, check_state
        )
        if cause is Cause.NONE:
            outcome.admissible.append(node)
        else:
            outcome.causes[node.name] = cause
            counts[cause] += 1

    # Cumulative survivors: all nodes minus everything rejected up to and
    # including this policy.
    survivors = len(nodes)
    for cause in FILTER_ORDER:
        survivors -= counts[cause]
        outcome.funnel[cause] = survivors

    return outcome


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


@dataclass
class Score:
    """The indicators for one candidate node."""

    node: str = ""
    delta: float = 0.0
    phi_prop: float = 1.0
    phi_transfer: float = 1.0
    total: float = 0.0
    remote_size: float = 0.0

    @property
    def is_ideal(self) -> bool:
        """A node whose properties match beta*(t) exactly: zero excess."""
        return self.delta == 0.0


def excess(
    node: Node,
    beta_star: Properties,
    max_levels: Properties,
    weights: dict[str, float] | None = None,
) -> tuple[float, float]:
    """Delta(n,t) and its maximum, the privilege granted beyond what is needed.

    A property already required at its top level cannot be exceeded, so it
    contributes neither to the excess nor to its normalisation; leaving it in
    would dilute the indicator with a term that is structurally zero.
    """
    weights = weights or {}
    delta = 0.0
    delta_max = 0.0

    for prop, top in max_levels.items():
        required = beta_star.get(prop, 0)
        if required >= top:
            continue
        weight = weights.get(prop, 1.0)
        offered = node.props.get(prop, 0)
        delta += weight * (offered - required) / (top - required)
        delta_max += weight

    return delta, delta_max


def score_node(
    node: Node,
    beta_star: Properties,
    datasets: list[Dataset],
    max_levels: Properties,
    w_prop: float,
    w_transfer: float,
    prop_weights: dict[str, float] | None = None,
) -> Score:
    """Evaluate both indicators for a candidate node.

    phi_prop rewards least privilege: it is 1 when the node offers exactly
    what the task needs. phi_transfer rewards data locality: it is 1 when
    every requested dataset is already on the node, so nothing has to cross
    the network and be exposed in transit.
    """
    delta, delta_max = excess(node, beta_star, max_levels, prop_weights)
    phi_prop = 1.0 - (delta / delta_max) if delta_max > 0 else 1.0

    total_size = sum(d.size for d in datasets)
    remote = sum(d.size for d in datasets if node.name not in d.local_nodes)
    phi_transfer = 1.0 - (remote / total_size) if total_size > 0 else 1.0

    return Score(
        node=node.name,
        delta=delta,
        phi_prop=phi_prop,
        phi_transfer=phi_transfer,
        total=w_prop * phi_prop + w_transfer * phi_transfer,
        remote_size=remote,
    )


def select(
    candidates: list[Node],
    beta_star: Properties,
    datasets: list[Dataset],
    max_levels: Properties,
    w_prop: float,
    w_transfer: float,
    rng: random.Random,
    prop_weights: dict[str, float] | None = None,
    tolerance: float = 1e-9,
) -> tuple[Score | None, bool]:
    """Pick the best node, breaking ties uniformly at random.

    The random tie-break matters more than it looks. Kubernetes picks
    uniformly among the nodes sharing the top score, and on a homogeneous
    cluster every node scores the same, so a deterministic choice would pile
    every task onto the same node and produce a contamination dynamic that
    the real scheduler never exhibits.

    Returns the chosen score and whether an ideal node was among the
    candidates.
    """
    if not candidates:
        return None, False

    scores = [
        score_node(n, beta_star, datasets, max_levels, w_prop, w_transfer, prop_weights)
        for n in candidates
    ]

    best = max(s.total for s in scores)
    top = [s for s in scores if s.total >= best - tolerance]
    ideal = any(s.is_ideal for s in scores)

    return rng.choice(top), ideal
