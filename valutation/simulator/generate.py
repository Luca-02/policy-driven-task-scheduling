"""Seeded generators for cluster, data, contexts and workload.

Everything a run needs is derived from ``(SimConfig, seed)``: the same pair
always produces the same scenario. Each concern draws from its own named
random stream, so changing the number of tasks does not perturb the cluster
and changing the conflict density does not perturb dataset placement. That
isolation is what makes a sweep a controlled experiment rather than a
collection of unrelated scenarios.

The cluster is built as a *template* replicated ``replication_factor`` times.
The template fixes the composition (which property classes exist, in what
proportion, in which locations); the replication factor fixes the size. Any
effect observed while varying the replication factor is therefore
attributable to scale and not to a change in composition.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from itertools import combinations, product

from config import SimConfig, Template
from model import (
    ClusterState,
    ConflictSet,
    Dataset,
    GeoGroup,
    Issuer,
    Node,
    Properties,
    Task,
)


@dataclass
class Scenario:
    """A fully materialised scenario: the cluster plus the batch to submit."""

    state: ClusterState
    batch: list[Task]
    template_names: list[str]
    locations: list[str]
    contexts: list[str]


def _stream(seed: int, name: str) -> random.Random:
    """An independent random stream for one concern.

    Seeding ``random.Random`` with a string is stable across processes and
    Python runs, unlike ``hash()``, which is salted per process.
    """
    return random.Random(f"{seed}:{name}")


# ---------------------------------------------------------------------------
# Geography
# ---------------------------------------------------------------------------


def make_geo(cfg: SimConfig) -> tuple[dict[str, GeoGroup], list[str], list[str]]:
    """Build the geographical hierarchy.

    Produces one group per region plus an umbrella group including them all,
    matching the eu / us / oecd shape of the prototype: regions carry explicit
    locations, the umbrella is defined by composition.

    Returns the groups, the flat list of locations, and the list of region
    group names.
    """
    groups: dict[str, GeoGroup] = {}
    locations: list[str] = []
    regions: list[str] = []

    for r in range(cfg.geo.n_regions):
        region = f"{cfg.geo.region_prefix}{r}"
        locs = {f"{region}-l{i}" for i in range(cfg.geo.locations_per_region)}
        groups[region] = GeoGroup(name=region, locations=locs)
        regions.append(region)
        locations.extend(sorted(locs))

    groups[cfg.geo.umbrella_name] = GeoGroup(
        name=cfg.geo.umbrella_name, includes=list(regions)
    )
    return groups, locations, regions


# ---------------------------------------------------------------------------
# Cluster
# ---------------------------------------------------------------------------


def _property_classes(cfg: SimConfig) -> list[Properties]:
    """Every property class a node may offer.

    Levels start at 1: a node at level 0 for a property offers nothing and
    could never host a task requiring it, which would be a degenerate member
    of the stratified template rather than an informative one. Level 0 remains
    valid for tasks and datasets, where it means "no requirement".
    """
    names = cfg.properties.names
    ranges = [range(1, cfg.properties.max_levels[p] + 1) for p in names]
    return [dict(zip(names, combo)) for combo in product(*ranges)]


def _draw_class(cfg: SimConfig, rng: random.Random) -> Properties:
    """Draw one property class for the REALISTIC template.

    Levels are skewed towards the bottom of the lattice: low-end nodes are
    common, high-end nodes are scarce, which is the interesting case because
    it is where c_prop actually restricts the pool.
    """
    props: Properties = {}
    for name in cfg.properties.names:
        top = cfg.properties.max_levels[name]
        levels = list(range(1, top + 1))
        weights = [top - lvl + 1 for lvl in levels]
        props[name] = rng.choices(levels, weights=weights, k=1)[0]
    return props


def make_template(
    cfg: SimConfig, locations: list[str], rng: random.Random
) -> list[Node]:
    """Build the cluster template: composition without size."""
    size = cfg.cluster.template_size
    nodes: list[Node] = []

    if cfg.cluster.template is Template.FLAT:
        classes = [dict(cfg.properties.max_levels) for _ in range(size)]

    elif cfg.cluster.template is Template.STRATIFIED:
        # Cover the lattice as evenly as the template size allows. Shuffling
        # first means the seed decides which node gets which class, while the
        # overall composition stays balanced.
        lattice = _property_classes(cfg)
        rng.shuffle(lattice)
        classes = [dict(lattice[i % len(lattice)]) for i in range(size)]

    else:  # REALISTIC
        classes = [_draw_class(cfg, rng) for _ in range(size)]

    # Locations are spread round-robin so that every location holds a similar
    # share of the cluster; the shuffle keeps class and location independent.
    order = list(range(size))
    rng.shuffle(order)
    for i, idx in enumerate(order):
        nodes.append(
            Node(
                name=f"t{idx}",
                props=classes[idx],
                loc=locations[i % len(locations)],
                capacity=cfg.cluster.slots_per_node,
            )
        )

    nodes.sort(key=lambda n: n.name)
    return nodes


def replicate(cfg: SimConfig, template: list[Node]) -> list[Node]:
    """Expand the template into the full cluster.

    Replica ``0`` keeps the template names so that dataset placement can be
    expressed on the template and optionally propagated.
    """
    nodes: list[Node] = []
    for r in range(cfg.cluster.replication_factor):
        for node in template:
            name = node.name if r == 0 else f"{node.name}-r{r}"
            nodes.append(
                Node(
                    name=name,
                    props=dict(node.props),
                    loc=node.loc,
                    capacity=cfg.cluster.slots_per_node,
                )
            )
    return nodes


# ---------------------------------------------------------------------------
# Contexts, issuers, conflicts
# ---------------------------------------------------------------------------


def make_contexts(
    cfg: SimConfig, rng: random.Random
) -> tuple[list[str], dict[str, Issuer], ConflictSet]:
    """Build contexts, issuers and the conflict graph X_conf.

    X_conf is drawn as a uniform random graph over the possible context pairs,
    with ``conflict_density`` the fraction of pairs it contains. Expressing it
    as a density rather than an absolute count keeps results comparable when
    the number of contexts changes.
    """
    contexts = [f"x{i}" for i in range(cfg.contexts.n_contexts)]

    issuers: dict[str, Issuer] = {}
    for i, _ in enumerate(contexts):
        auth = set(rng.sample(contexts, min(cfg.contexts.auth_size, len(contexts))))
        # With auth_size == 1 the natural reading is one issuer per context;
        # keep that correspondence rather than drawing at random.
        if cfg.contexts.auth_size == 1:
            auth = {contexts[i]}
        name = f"i{i}"
        issuers[name] = Issuer(name=name, auth=auth)

    conflicts = ConflictSet()
    all_pairs = list(combinations(contexts, 2))
    n_pairs = round(cfg.contexts.conflict_density * len(all_pairs))
    for a, b in rng.sample(all_pairs, min(n_pairs, len(all_pairs))):
        conflicts.add(a, b)

    return contexts, issuers, conflicts


# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------


def _dominates(props: Properties, required: Properties) -> bool:
    return all(props.get(p, 0) >= lvl for p, lvl in required.items())


def _draw_requirement(
    weights: list[float], max_levels: Properties, rng: random.Random
) -> Properties:
    """Draw a requirement level for each property, from weighted levels.

    ``weights[k]`` is the relative frequency of level ``k``, starting at 0
    ("no requirement"). The list is truncated to each property's own top
    level, so properties with fewer levels stay consistent with the same
    configuration.

    Weights matter more than they look. beta*(t) is a least upper bound over
    every property of every requested dataset, so it aggregates
    ``|P| x |req(t)|`` independent draws: a level drawn 2% of the time
    individually ends up as the effective requirement of roughly a fifth of
    the tasks. A hard ceiling cannot express that, since it would make the
    top level either impossible or as likely as any other.
    """
    props: Properties = {}
    for name, top in max_levels.items():
        levels = list(range(0, top + 1))
        w = list(weights[: top + 1]) or [1.0]
        if len(w) < len(levels):  # pad if fewer weights than levels
            w += [w[-1]] * (len(levels) - len(w))
        props[name] = rng.choices(levels, weights=w, k=1)[0]
    return props


def make_datasets(
    cfg: SimConfig,
    template: list[Node],
    all_nodes: list[Node],
    contexts: list[str],
    regions: list[str],
    rng: random.Random,
    placement_rng: random.Random,
) -> dict[str, Dataset]:
    """Build the dataset population and place it on the cluster.

    Attributes and placement are drawn in two passes from two independent
    streams. Placement necessarily depends on the cluster, since data can only
    sit on nodes that can host it; drawing it from the same stream as the
    attributes would let the cluster composition perturb which contexts,
    jurisdictions and sizes the datasets get, and two templates would then
    differ in more than the one variable under study.

    Placement is drawn among *template* nodes and then, if
    ``replicate_placement`` is set, propagated to the corresponding nodes of
    every replica. Leaving it unpropagated is what exposes the interaction
    between horizontal node redundancy and static data: adding replicas grows
    the cluster but not the set of nodes allowed to run a task pinned to where
    its data already sits.

    Placement candidates are restricted to template nodes that satisfy the
    dataset's own beta(d). Placing data on nodes that cannot host it would
    make every task requesting it unschedulable, which is an artefact of the
    generator rather than a property of the model.
    """
    by_template: dict[str, list[Node]] = {}
    for node in all_nodes:
        base = node.name.split("-r")[0]
        by_template.setdefault(base, []).append(node)

    # Pass 1: attributes, independent of the cluster.
    attributes = []
    for i in range(cfg.datasets.n_datasets):
        props = _draw_requirement(
            cfg.datasets.beta_weights, cfg.properties.max_levels, rng
        )

        if rng.random() < cfg.datasets.public_fraction:
            ctx: set[str] = set()
        else:
            ctx = {rng.choice(contexts)}

        if rng.random() < cfg.datasets.geo_umbrella_fraction:
            geo = cfg.geo.umbrella_name
        else:
            geo = rng.choice(regions)

        is_static = rng.random() < cfg.datasets.static_fraction
        size = rng.uniform(cfg.datasets.size_min, cfg.datasets.size_max)
        attributes.append((f"d{i}", props, ctx, geo, is_static, size))

    # Pass 2: placement, which must depend on the cluster.
    datasets: dict[str, Dataset] = {}
    for name, props, ctx, geo, is_static, size in attributes:
        eligible = [n for n in template if _dominates(n.props, props)] or list(template)
        k = min(cfg.datasets.placement_replication, len(eligible))
        chosen = placement_rng.sample(eligible, k)

        local: set[str] = set()
        for node in chosen:
            if cfg.datasets.replicate_placement:
                local.update(n.name for n in by_template[node.name])
            else:
                local.add(node.name)

        datasets[name] = Dataset(
            name=name,
            props=props,
            geo=geo,
            contexts=ctx,
            size=size,
            is_static=is_static,
            local_nodes=local,
        )

    return datasets


# ---------------------------------------------------------------------------
# Workload
# ---------------------------------------------------------------------------


def make_batch(
    cfg: SimConfig,
    datasets: dict[str, Dataset],
    issuers: dict[str, Issuer],
    regions: list[str],
    rng: random.Random,
) -> list[Task]:
    """Build the ordered batch of tasks.

    Tasks are generated so that c_auth never fires: an issuer only ever
    requests datasets whose contexts it is authorised for. c_auth does not
    depend on the cluster configuration, so letting it reject tasks would
    measure the generator's distribution rather than any property of the
    model. This is a deliberate design choice and belongs in the methodology
    section.

    Task requirements are drawn low by default: beta*(t) is then mostly
    determined by the datasets, which is the amplification effect the model
    predicts.
    """
    issuer_names = sorted(issuers)

    # Which datasets each issuer may request, precomputed once.
    eligible: dict[str, list[str]] = {}
    for name, issuer in issuers.items():
        eligible[name] = [
            d.name for d in datasets.values() if d.contexts <= issuer.auth
        ]

    usable = [n for n in issuer_names if len(eligible[n]) >= cfg.workload.req_min]
    if not usable:
        raise ValueError(
            "no issuer can request the minimum number of datasets; "
            "increase n_datasets or public_fraction, or lower req_min"
        )

    batch: list[Task] = []
    for i in range(cfg.workload.n_tasks):
        issuer = rng.choice(usable)
        pool = eligible[issuer]
        size = rng.randint(cfg.workload.req_min, cfg.workload.req_max)
        req = rng.sample(pool, min(size, len(pool)))

        props = _draw_requirement(
            cfg.workload.beta_weights, cfg.properties.max_levels, rng
        )

        geo = rng.choice(regions) if rng.random() < cfg.workload.geo_fraction else None

        batch.append(
            Task(
                name=f"task{i}",
                issuer=issuer,
                req_datasets=req,
                props=props,
                geo=geo,
            )
        )

    return batch


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def generate(cfg: SimConfig, seed: int | None = None) -> Scenario:
    """Materialise a complete scenario from a configuration and a seed."""
    seed = cfg.seed if seed is None else seed

    groups, locations, regions = make_geo(cfg)

    template = make_template(cfg, locations, _stream(seed, "cluster"))
    nodes = replicate(cfg, template)

    contexts, issuers, conflicts = make_contexts(cfg, _stream(seed, "contexts"))

    datasets = make_datasets(
        cfg,
        template,
        nodes,
        contexts,
        regions,
        _stream(seed, "datasets"),
        _stream(seed, "placement"),
    )

    batch = make_batch(cfg, datasets, issuers, regions, _stream(seed, "workload"))

    state = ClusterState(
        nodes={n.name: n for n in nodes},
        datasets=datasets,
        issuers=issuers,
        geo_groups=groups,
        conflicts=conflicts,
        max_levels=dict(cfg.properties.max_levels),
    )

    return Scenario(
        state=state,
        batch=batch,
        template_names=[n.name for n in template],
        locations=locations,
        contexts=contexts,
    )
