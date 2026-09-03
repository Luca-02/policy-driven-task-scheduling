"""Output schema.

Two record types, one per driver:

* ``TaskRecord``  - one row per task, written by both drivers. Part A leaves
  the state-dependent fields empty; Part B fills them.
* ``StepRecord``  - one row per step of a batch, written by the stateful
  driver only. Feeds the saturation and node-availability figures.

Records are written in long format: every configuration parameter is repeated
on every row. Aggregation happens at analysis time, never at write time, so
that a new statistic never requires re-running a sweep.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields

from model import Cause


@dataclass
class TaskRecord:
    """Outcome of a single task."""

    # -- identity ---------------------------------------------------------
    sweep: str = ""
    task: str = ""
    issuer: str = ""
    step: int = 0

    # -- request shape ----------------------------------------------------
    n_datasets: int = 0
    n_static_datasets: int = 0
    beta_star: str = ""  # JSON, for inspection rather than plotting
    beta_star_sum: int = 0  # scalar proxy of how demanding beta*(t) is
    geo_star_size: int = 0
    ctx_star_size: int = 0
    total_size: float = 0.0

    # -- funnel: nodes surviving each policy, cumulatively -----------------
    n_nodes: int = 0
    n_after_prop: int = 0
    n_after_geo: int = 0
    n_after_static: int = 0
    n_after_sanitizing: int = 0
    n_after_wall: int = 0
    n_admissible: int = 0  # after every policy and simulator constraint

    # -- outcome ----------------------------------------------------------
    assigned: bool = False
    assigned_node: str = ""
    cause: str = Cause.NONE.value
    blocked_by_state: bool = False  # rejected only because of Lambda(n)
    # or occupancy, i.e. would have been
    # admissible on a clean, idle cluster

    # -- quality of the assignment ----------------------------------------
    delta: float = 0.0  # privilege excess of the chosen node
    phi_prop: float = 0.0
    phi_transfer: float = 0.0
    score: float = 0.0
    ideal_exists: bool = False  # a node with alpha(n) = beta*(t) was available
    remote_size: float = 0.0  # size(remote(f(t), t))

    # -- state at decision time (Part B only) -----------------------------
    mean_footprint: float = 0.0
    n_sanitizing: int = 0
    occupied_slots: int = 0

    @staticmethod
    def columns() -> list[str]:
        return [f.name for f in fields(TaskRecord)]

    def as_row(self) -> dict:
        return asdict(self)


@dataclass
class StepRecord:
    """Cluster state at the end of one step of a batch."""

    sweep: str = ""
    step: int = 0
    mean_footprint: float = 0.0
    max_footprint: int = 0
    n_sanitizing: int = 0
    n_available: int = 0
    occupied_slots: int = 0
    cumulative_blocked: int = 0
    cumulative_assigned: int = 0

    @staticmethod
    def columns() -> list[str]:
        return [f.name for f in fields(StepRecord)]

    def as_row(self) -> dict:
        return asdict(self)


@dataclass
class RunResult:
    """Everything one (config, seed) pair produces."""

    tasks: list[TaskRecord] = field(default_factory=list)
    steps: list[StepRecord] = field(default_factory=list)
