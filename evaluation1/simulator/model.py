"""Domain types for the formal model.

This module holds the entities of the model defined in Chapter 3 (nodes,
datasets, tasks, issuers, geographical groups) plus the two pieces of mutable
state the model exposes: the contextual footprint Lambda(n) and, as a
simulator-only addition, node occupancy.

Nothing in this module makes scheduling decisions. Policy evaluation lives in
``policies.py`` so that the reference implementation of the model stays
separable from the simulation machinery built around it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# A property assignment maps a property name to its level.
# Used for alpha(n), beta(t) and beta(d) alike. A missing property means
# level 0, i.e. the property is not offered / not required.
Properties = dict[str, int]

# Sentinel meaning "no capacity limit" for a node.
UNLIMITED = -1


class Cause(str, Enum):
    """Why a task was not assigned, or why a node was excluded.

    The first three values are translation-time rejections raised before any
    node is inspected; the rest are per-node exclusion reasons collected
    during filtering. ``CAPACITY`` and ``SANITIZING`` are simulator-only:
    they do not appear in the formal model, which has no notion of node
    occupancy or of a node being temporarily out of N.
    """

    NONE = "none"

    # Translation-time rejections (whole task, no node inspected)
    AUTH = "auth"  # c_auth: issuer not authorised for ctx(d)
    GEO_EMPTY = "geo_empty"  # geo*(t) = empty set
    STATIC_EMPTY = "static_empty"  # intersection of lambda(d) is empty

    # Per-node exclusions during filtering
    PROP = "prop"  # c_prop: alpha(n) does not dominate beta*(t)
    GEO = "geo"  # c_geo: loc(n) not in geo*(t)
    STATIC = "static"  # c_static: node not in intersection lambda(d)
    WALL = "wall"  # c_wall: conflict with Lambda(n)

    # Simulator-only exclusions
    CAPACITY = "capacity"  # no free slot on the node
    SANITIZING = "sanitizing"  # node temporarily out of N

    @property
    def policy(self) -> str:
        """The policy this cause belongs to.

        Translation-time and filter-time rejections of the same policy map to
        the same name, so that results can be attributed per policy. The
        distinction between the two is preserved by ``is_translation``,
        because the two have different mitigations: an empty intersection is
        fixed by replicating data, an excluded node by adding nodes where the
        data already is.
        """
        return _POLICY_OF[self]

    @property
    def is_translation(self) -> bool:
        """True if the rejection happens before any node is inspected."""
        return self in (Cause.AUTH, Cause.GEO_EMPTY, Cause.STATIC_EMPTY)


_POLICY_OF: dict[Cause, str] = {
    Cause.NONE: "none",
    Cause.AUTH: "c_auth",
    Cause.GEO_EMPTY: "c_geo",
    Cause.GEO: "c_geo",
    Cause.STATIC_EMPTY: "c_static",
    Cause.STATIC: "c_static",
    Cause.PROP: "c_prop",
    Cause.WALL: "c_wall",
    Cause.CAPACITY: "capacity",
    Cause.SANITIZING: "sanitizing",
}


@dataclass
class GeoGroup:
    """A geographical group: a set of locations, possibly composed of others.

    Mirrors the GeographicalGroup CRD, which allows a group to be defined
    either by an explicit list of locations or by the union of other groups.
    """

    name: str
    locations: set[str] = field(default_factory=set)
    includes: list[str] = field(default_factory=list)


@dataclass
class Node:
    """A computational node.

    Attributes:
        name: node identifier.
        props: alpha(n), the property levels offered by the node.
        loc: loc(n), the physical location of the node.
        capacity: maximum number of concurrently running tasks, or UNLIMITED.
            Simulator-only; the formal model places no bound here.
        lambda_ctx: Lambda(n), the contextual footprint left by past tasks.
        active_until: end step of each currently occupied slot. Its length is
            the number of running tasks, so free slots are
            ``capacity - len(active_until)``.
        sanitizing: whether the node is currently undergoing sanitization and
            is therefore temporarily out of N.
        sanitize_since: step at which sanitization started, for availability
            accounting.
    """

    name: str
    props: Properties
    loc: str
    capacity: int = UNLIMITED
    lambda_ctx: set[str] = field(default_factory=set)
    active_until: list[int] = field(default_factory=list)
    sanitizing: bool = False
    sanitize_since: int | None = None

    # -- occupancy ---------------------------------------------------------

    def release_finished(self, step: int) -> None:
        """Free every slot whose task has finished by ``step``."""
        self.active_until = [end for end in self.active_until if end > step]

    @property
    def running(self) -> int:
        return len(self.active_until)

    @property
    def is_idle(self) -> bool:
        return not self.active_until

    def has_free_slot(self) -> bool:
        if self.capacity == UNLIMITED:
            return True
        return len(self.active_until) < self.capacity

    def occupy(self, until: int) -> None:
        self.active_until.append(until)

    # -- contextual footprint ---------------------------------------------

    def deposit(self, contexts: set[str]) -> None:
        """Lambda(n) <- Lambda(n) union ctx*(t), performed after binding."""
        self.lambda_ctx |= contexts

    def clear_traces(self) -> None:
        """Lambda(n) <- empty set, the effect of a completed sanitization."""
        self.lambda_ctx.clear()


@dataclass
class Dataset:
    """A dataset requested by tasks.

    ``local_nodes`` is lambda(d) and is meaningful for both static and
    non-static datasets: for a static dataset it is a hard placement
    constraint, for a non-static one it tells where replicas already are and
    therefore drives phi_transfer.
    """

    name: str
    props: Properties  # beta(d)
    geo: str | None  # geo(d), a geographical group name
    contexts: set[str]  # ctx(d)
    size: float  # size(d), in MB
    is_static: bool
    local_nodes: set[str]  # lambda(d)


@dataclass
class Issuer:
    """A subject submitting tasks, with its authorisation perimeter auth(i)."""

    name: str
    auth: set[str]


@dataclass
class Task:
    """A computation to be scheduled."""

    name: str
    issuer: str  # iss(t)
    req_datasets: list[str]  # req(t)
    props: Properties  # beta(t)
    geo: str | None  # geo(t), a geographical group name


@dataclass
class ConflictSet:
    """X_conf, the symmetric set of conflicting context pairs."""

    pairs: set[frozenset[str]] = field(default_factory=set)

    def add(self, a: str, b: str) -> None:
        if a != b:
            self.pairs.add(frozenset((a, b)))

    def conflicts(self, a: str, b: str) -> bool:
        return frozenset((a, b)) in self.pairs

    def any_conflict(self, left: set[str], right: set[str]) -> bool:
        """True if (left x right) intersects X_conf.

        This is the c_wall test, with ``left`` the issuer perimeter auth(i)
        and ``right`` the node footprint Lambda(n).
        """
        for a in left:
            for b in right:
                if a != b and frozenset((a, b)) in self.pairs:
                    return True
        return False

    def __len__(self) -> int:
        return len(self.pairs)


@dataclass
class ClusterState:
    """Everything the scheduler needs to decide, plus the current step.

    ``step`` is the simulator's discrete clock: one step corresponds to one
    submitted task. It has no counterpart in the formal model and is never
    interpreted as wall-clock time; absolute latencies are measured on the
    prototype, not here.
    """

    nodes: dict[str, Node]
    datasets: dict[str, Dataset]
    issuers: dict[str, Issuer]
    geo_groups: dict[str, GeoGroup]
    conflicts: ConflictSet
    max_levels: Properties
    step: int = 0

    def available_nodes(self) -> list[Node]:
        """Nodes currently in N: every node not undergoing sanitization."""
        return [n for n in self.nodes.values() if not n.sanitizing]

    def release_finished(self) -> None:
        for node in self.nodes.values():
            node.release_finished(self.step)

    def mean_footprint(self) -> float:
        if not self.nodes:
            return 0.0
        return sum(len(n.lambda_ctx) for n in self.nodes.values()) / len(self.nodes)

    def sanitizing_count(self) -> int:
        return sum(1 for n in self.nodes.values() if n.sanitizing)

    def occupied_slots(self) -> int:
        return sum(n.running for n in self.nodes.values())
