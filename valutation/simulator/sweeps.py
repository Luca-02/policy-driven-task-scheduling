"""Experiment grids.

Each experiment is a small deviation from the baseline configuration along
one axis, replicated over several seeds. The varying parameters are written
as columns next to every record, in long format, so that aggregation happens
at analysis time and a new statistic never requires re-running anything.

Usage:
    python3 sweeps.py            # run everything
    python3 sweeps.py conflicts  # run one experiment
    python3 sweeps.py --list     # show what is defined
"""

from __future__ import annotations

import csv
import gzip
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from config import BASELINE, SanitizationStrategy, SimConfig, Template
from drivers import evaluate_space, run_batch
from model import UNLIMITED
from records import StepRecord, TaskRecord

OUT = Path(".tmp/results")
SEEDS = 100

# Independent samples suffice for the stateless experiments; the stateful ones
# need a long enough sequence for the footprint to saturate.
N_TASKS_STATELESS = 1000
N_TASKS_STATEFUL = 2000

Grid = list[tuple[dict, SimConfig]]


@dataclass
class Experiment:
    name: str
    title: str
    stateful: bool
    grid: Callable[[], Grid]
    record_steps: bool = False


# ---------------------------------------------------------------------------
# Stateless experiments: the solution space on a clean cluster
# ---------------------------------------------------------------------------

_A = BASELINE.replace(**{"workload.n_tasks": N_TASKS_STATELESS})


def grid_policy_funnel() -> Grid:
    """How far each policy narrows the pool, by request size and cluster mix."""
    out: Grid = []
    for template in Template:
        for req in (1, 2, 3, 4, 5):
            out.append(
                (
                    {"template": template.value, "req_size": req},
                    _A.replace(
                        **{
                            "cluster.template": template,
                            "workload.req_min": req,
                            "workload.req_max": req,
                        }
                    ),
                )
            )
    return out


def grid_cluster_composition() -> Grid:
    """Admissibility against privilege excess, across cluster compositions."""
    return [
        ({"template": t.value}, _A.replace(**{"cluster.template": t})) for t in Template
    ]


def grid_static_data() -> Grid:
    """How static data and its replication affect combinatorial rejection."""
    out: Grid = []
    for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
        for replication in (1, 2, 3, 4, 5):
            out.append(
                (
                    {"static_fraction": fraction, "data_replication": replication},
                    _A.replace(
                        **{
                            "datasets.static_fraction": fraction,
                            "datasets.placement_replication": replication,
                        }
                    ),
                )
            )
    return out


def grid_scale() -> Grid:
    """Whether growing the cluster relaxes each policy.

    Two things called "replication" are varied here, and they are different:

    ``replication_factor`` replicates the *nodes*. The cluster is built as a
    template whose composition is fixed (which property classes exist, in
    what proportion, in which locations) and then copied k times. Doubling it
    doubles every class and every location, so composition stays constant and
    any observed effect is attributable to size alone.

    ``replicate_placement`` decides what happens to the *data* when the nodes
    are replicated:

    - True  ("i dati seguono i nodi"): each copy of a template node also
      receives the datasets that node held. Growing the cluster grows the set
      of nodes holding any given dataset.
    - False ("i dati restano fermi"): only the original template nodes hold
      the data. Growing the cluster adds compute capacity but not storage
      locations, which is what happens in practice when nodes are added
      without touching the storage layer.

    The distinction only bites for *static* datasets, which cannot be
    transferred: a task requesting them is confined to the nodes that already
    hold them. For non-static datasets it merely changes phi_transfer, since
    a remote copy can always be fetched.
    """
    out: Grid = []
    for factor in (1, 2, 4, 8):
        for propagate in (True, False):
            out.append(
                (
                    {"replication_factor": factor, "data_follows_nodes": propagate},
                    _A.replace(
                        **{
                            "cluster.replication_factor": factor,
                            "datasets.replicate_placement": propagate,
                        }
                    ),
                )
            )
    return out


# ---------------------------------------------------------------------------
# Stateful experiments: how the state evolves along a batch
# ---------------------------------------------------------------------------

_B = BASELINE.replace(**{"workload.n_tasks": N_TASKS_STATEFUL})


def grid_conflicts() -> Grid:
    """How competition between organisations degrades schedulability."""
    return [
        ({"conflict_density": rho}, _B.replace(**{"contexts.conflict_density": rho}))
        for rho in (0.0, 0.05, 0.1, 0.2, 0.4, 0.5)
    ]


def grid_sanitization() -> Grid:
    """The periodic period, swept finely, plus the threshold trigger for comparison.

    The period is explored at high resolution because it traces out a U-shaped
    cost curve: too short and nodes spend most of their time out of N, too
    long and the footprint saturates before the next sanitization. The
    threshold trigger is included at a handful of values to check whether a
    differently-shaped trigger beats a well-chosen period; it does not turn
    out to.
    """
    periods = (10, 20, 30, 50, 75, 100, 150, 200)
    thresholds = (1, 2, 3)

    out: Grid = []
    for rho in (0.05, 0.1, 0.2):
        out.append(
            (
                {
                    "strategy": "none",
                    "period": 0,
                    "threshold": 0,
                    "conflict_density": rho,
                },
                _B.replace(
                    **{
                        "sanitization.strategy": SanitizationStrategy.NONE,
                        "contexts.conflict_density": rho,
                    }
                ),
            )
        )
        for period in periods:
            out.append(
                (
                    {
                        "strategy": "periodic",
                        "period": period,
                        "threshold": 0,
                        "conflict_density": rho,
                    },
                    _B.replace(
                        **{
                            "sanitization.strategy": SanitizationStrategy.PERIODIC,
                            "sanitization.period": period,
                            "contexts.conflict_density": rho,
                        }
                    ),
                )
            )
        for threshold in thresholds:
            out.append(
                (
                    {
                        "strategy": "threshold",
                        "period": 0,
                        "threshold": threshold,
                        "conflict_density": rho,
                    },
                    _B.replace(
                        **{
                            "sanitization.strategy": SanitizationStrategy.THRESHOLD,
                            "sanitization.threshold": threshold,
                            "contexts.conflict_density": rho,
                        }
                    ),
                )
            )
    return out


def grid_redundancy() -> Grid:
    """Whether adding nodes mitigates blocking, and when it stops helping."""
    out: Grid = []
    for factor in (1, 2, 4, 8):
        for propagate in (True, False):
            out.append(
                (
                    {"replication_factor": factor, "data_follows_nodes": propagate},
                    _B.replace(
                        **{
                            "cluster.replication_factor": factor,
                            "datasets.replicate_placement": propagate,
                            "contexts.conflict_density": 0.2,
                        }
                    ),
                )
            )
    return out


def grid_occupancy() -> Grid:
    """Contention for node slots, and how it combines with isolation."""
    out: Grid = []
    for slots in (1, 2, 4, UNLIMITED):
        for duration in (5, 20):
            out.append(
                (
                    {"slots_per_node": slots, "duration": duration},
                    _B.replace(
                        **{
                            "cluster.slots_per_node": slots,
                            "workload.duration": duration,
                            "contexts.conflict_density": 0.2,
                        }
                    ),
                )
            )
    return out


def grid_amplification() -> Grid:
    """Whether a narrower pool makes isolation bite harder."""
    return [
        (
            {"template": t.value},
            _B.replace(**{"cluster.template": t, "contexts.conflict_density": 0.2}),
        )
        for t in Template
    ]


# Esperimenti effettivamente eseguiti dal capitolo di valutazione. Le funzioni
# grid_cluster_composition, grid_occupancy e grid_amplification restano
# definite sopra e producono risultati validi se rieseguite, ma sono escluse
# da questo elenco: i risultati che misuravano non sono stati inclusi nella
# stesura finale del capitolo. Per riattivarne una, aggiungerla qui sotto.
EXPERIMENTS: list[Experiment] = [
    Experiment("policy_funnel", "Policy funnel", False, grid_policy_funnel),
    Experiment("static_data", "Static data placement", False, grid_static_data),
    Experiment("scale", "Cluster scale", False, grid_scale),
    Experiment("conflicts", "Conflict density", True, grid_conflicts),
    Experiment(
        "sanitization", "Sanitization strategies", True, grid_sanitization, True
    ),
    Experiment("redundancy", "Node redundancy", True, grid_redundancy),
]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _write(path: Path, columns: list[str], rows: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with gzip.open(path, "wt", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


def run_experiment(exp: Experiment, seeds: int = SEEDS) -> None:
    grid = exp.grid()
    driver = run_batch if exp.stateful else evaluate_space

    param_keys: list[str] = sorted({k for params, _ in grid for k in params})
    task_cols = ["experiment", *param_keys, "seed", *TaskRecord.columns()]
    step_cols = ["experiment", *param_keys, "seed", *StepRecord.columns()]

    task_rows: list[dict] = []
    step_rows: list[dict] = []

    start = time.perf_counter()
    for params, cfg in grid:
        prefix = {"experiment": exp.name, **{k: params.get(k, "") for k in param_keys}}
        for seed in range(seeds):
            result = driver(cfg, seed=seed, sweep=exp.name)
            for record in result.tasks:
                task_rows.append({**prefix, "seed": seed, **record.as_row()})
            if exp.record_steps:
                for record in result.steps:
                    step_rows.append({**prefix, "seed": seed, **record.as_row()})

    n = _write(OUT / f"{exp.name}_tasks.csv.gz", task_cols, task_rows)
    message = f"{exp.name:22s} {len(grid):3d} config x {seeds} semi -> {n:>7} righe"
    if exp.record_steps:
        m = _write(OUT / f"{exp.name}_steps.csv.gz", step_cols, step_rows)
        message += f" + {m} passi"
    print(f"{message}  [{time.perf_counter() - start:.1f}s]")


def main(argv: list[str]) -> int:
    if "--list" in argv:
        for exp in EXPERIMENTS:
            print(f"{exp.name:22s} {exp.title}")
        return 0

    wanted = [a for a in argv if not a.startswith("-")]
    selected = [e for e in EXPERIMENTS if not wanted or e.name in wanted]
    if not selected:
        print(f"nessun esperimento corrisponde a {wanted}")
        return 1

    for exp in selected:
        run_experiment(exp)
    print(f"\nrisultati in {OUT.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
