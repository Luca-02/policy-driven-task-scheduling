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

import pandas as pd
from typing import Callable, Iterable

from config import BASELINE, SanitizationStrategy, SimConfig, Template
from drivers import (
    evaluate_prefixes,
    evaluate_property_dimensionality,
    evaluate_space,
    run_batch,
)
from model import UNLIMITED
from records import StepRecord, TaskRecord

OUT = Path(".tmp/results")
SEEDS = 10

# Independent samples suffice for the stateless experiments; the stateful ones
# need a long enough sequence for the footprint to saturate.
N_TASKS_STATELESS = 1000
N_TASKS_STATEFUL = 2000

Grid = list[tuple[dict, SimConfig]]

# Cluster compositions actually evaluated. The flat template, in which every
# node offers the maximum level of every property, is excluded on purpose:
# c_prop can never exclude a node there, so it contributes a constant 100%
# line to every figure and no information about the policy. The comparison
# that carries meaning is between a cluster whose classes are spread evenly
# over the lattice and one skewed towards the low end.
TEMPLATES = (Template.STRATIFIED, Template.REALISTIC)


@dataclass
class Experiment:
    name: str
    title: str
    stateful: bool
    grid: Callable[[], Grid]
    record_steps: bool = False
    # Overrides the driver chosen from ``stateful``. Used by the paired
    # prefix design, which is stateless but not the plain per-task driver.
    driver: Callable | None = None

    def resolve_driver(self) -> Callable:
        if self.driver is not None:
            return self.driver
        return run_batch if self.stateful else evaluate_space


# ---------------------------------------------------------------------------
# Stateless experiments: the solution space on a clean cluster
# ---------------------------------------------------------------------------

_A = BASELINE.replace(**{"workload.n_tasks": N_TASKS_STATELESS})


# Longest prefix evaluated by the paired funnel design.
MAX_PREFIX = 5


def grid_policy_funnel() -> Grid:
    """How far each policy narrows the pool, by request size and cluster mix.

    Paired design: every task is generated with MAX_PREFIX datasets and run
    through ``evaluate_prefixes``, which evaluates the prefixes of length
    1..MAX_PREFIX of that same request. Request size therefore varies inside
    each run rather than across configurations, and is recovered at analysis
    time from the ``n_datasets`` column. Only the cluster composition varies
    across the grid.
    """
    return [
        (
            {"template": template.value},
            _A.replace(
                **{
                    "cluster.template": template,
                    "workload.req_min": MAX_PREFIX,
                    "workload.req_max": MAX_PREFIX,
                }
            ),
        )
        for template in TEMPLATES
    ]


def grid_cluster_composition() -> Grid:
    """Admissibility against privilege excess, across cluster compositions."""
    return [
        ({"template": t.value}, _A.replace(**{"cluster.template": t}))
        for t in TEMPLATES
    ]


# Properties used by the isolated c_prop experiment. Larger than the
# reference configuration on purpose: the point is to trace how
# admissibility decays as the lattice gains dimensions, which needs a few
# more points than the three properties of the reference cluster.
PROPERTY_AXIS = {f"p{i}": 3 for i in range(1, 6)}


def grid_property_dimensionality() -> Grid:
    """How much c_prop alone costs for each property added to the model.

    Only the cluster composition varies across the grid; the number of
    properties varies inside each run, by projection, and is recovered from
    the ``n_properties`` column.
    """
    return [
        (
            {"template": template.value},
            _A.replace(
                **{
                    "cluster.template": template,
                    "properties.max_levels": dict(PROPERTY_AXIS),
                    "workload.n_tasks": 1,
                }
            ),
        )
        for template in TEMPLATES
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
    for factor in (1, 2, 3, 4, 6, 8):
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
        for rho in (0.0, 0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5)
    ]


def grid_sanitization() -> Grid:
    """The three sanitization triggers, over the parameters that govern them.

    The periodic period S is swept from very short to long because it traces
    out a U-shaped cost curve: sanitize too often and nodes spend much of
    their time out of N, sanitize too rarely and the footprint saturates
    between one sweep and the next. Resolving the left arm of the U needs
    periods well below ten steps, which is why the sweep starts at 2.

    The threshold theta is swept over the whole meaningful range: theta = 1
    sanitizes on the first trace deposited, larger values tolerate a growing
    footprint before intervening.

    The combined trigger fires on whichever condition comes first, so it
    reacts early to the nodes that accumulate fastest while still putting a
    ceiling on how long any trace survives. It is swept on both parameters
    around the region where the two pure strategies do best.
    """
    periods = (2, 4, 8, 15, 25, 40, 65, 110, 180, 300)
    thresholds = (1, 2, 3, 4, 5, 6)
    combined = ((25, 2), (25, 4), (65, 2), (65, 4), (180, 2), (180, 4))

    out: Grid = []
    for rho in (0.05, 0.15, 0.3):
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
        for period, threshold in combined:
            out.append(
                (
                    {
                        "strategy": "combined",
                        "period": period,
                        "threshold": threshold,
                        "conflict_density": rho,
                    },
                    _B.replace(
                        **{
                            "sanitization.strategy": SanitizationStrategy.PERIODIC_THRESHOLD,
                            "sanitization.period": period,
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
    for factor in (1, 2, 3, 4, 6, 8):
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
        for t in TEMPLATES
    ]


# Experiments run by the evaluation chapter. grid_cluster_composition,
# grid_occupancy and grid_amplification remain defined above and still work
# if re-enabled, but are left out of this list: the results they measured are
# not part of the final write-up.
EXPERIMENTS: list[Experiment] = [
    Experiment(
        "policy_funnel",
        "Policy funnel",
        False,
        grid_policy_funnel,
        driver=evaluate_prefixes,
    ),
    Experiment(
        "property_dimensionality",
        "c_prop in isolation",
        False,
        grid_property_dimensionality,
        driver=evaluate_property_dimensionality,
    ),
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


def run_experiment(
    exp: Experiment, seeds: int = SEEDS, offset: int = 0, suffix: str = ""
) -> None:
    grid = exp.grid()
    driver = exp.resolve_driver()

    param_keys: list[str] = sorted({k for params, _ in grid for k in params})
    task_cols = ["experiment", *param_keys, "seed", *TaskRecord.columns()]
    step_cols = ["experiment", *param_keys, "seed", *StepRecord.columns()]

    task_rows: list[dict] = []
    step_rows: list[dict] = []

    start = time.perf_counter()
    for params, cfg in grid:
        prefix = {"experiment": exp.name, **{k: params.get(k, "") for k in param_keys}}
        for seed in range(offset, offset + seeds):
            result = driver(cfg, seed=seed, sweep=exp.name)
            for record in result.tasks:
                task_rows.append({**prefix, "seed": seed, **record.as_row()})
            if exp.record_steps:
                for record in result.steps:
                    step_rows.append({**prefix, "seed": seed, **record.as_row()})

    n = _write(OUT / f"{exp.name}_tasks{suffix}.csv.gz", task_cols, task_rows)
    message = f"{exp.name:22s} {len(grid):3d} config x {seeds} semi -> {n:>7} righe"
    if exp.record_steps:
        m = _write(OUT / f"{exp.name}_steps{suffix}.csv.gz", step_cols, step_rows)
        message += f" + {m} passi"
    print(f"{message}  [{time.perf_counter() - start:.1f}s]")


# Merges the per-chunk files produced by a chunked run into a single file.
def merge_chunks(nome: str) -> None:
    import glob

    for tipo in ("tasks", "steps"):
        parti = sorted(glob.glob(str(OUT / f"{nome}_{tipo}_s*.csv.gz")))
        if not parti:
            continue
        frames = [pd.read_csv(parte) for parte in parti]
        unito = pd.concat(frames, ignore_index=True)
        unito.to_csv(OUT / f"{nome}_{tipo}.csv.gz", index=False, compression="gzip")
        for parte in parti:
            Path(parte).unlink()
        print(f"{nome}_{tipo}: {len(parti)} blocchi uniti, {len(unito)} righe")


def main(argv: list[str]) -> int:
    if "--merge" in argv:
        for nome in [a for a in argv if not a.startswith("-")]:
            merge_chunks(nome)
        return 0

    seeds, offset, suffix = SEEDS, 0, ""
    if "--seeds" in argv:
        i = argv.index("--seeds")
        seeds = int(argv[i + 1])
        offset = int(argv[i + 2])
        suffix = f"_s{offset:03d}"
        argv = argv[:i] + argv[i + 3 :]

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
        run_experiment(exp, seeds=seeds, offset=offset, suffix=suffix)
    print(f"\nrisultati in {OUT.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
