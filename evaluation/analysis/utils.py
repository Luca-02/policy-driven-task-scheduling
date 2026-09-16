"""
utils.py: shared loading and analysis helpers for the evaluation notebooks.

Used by both impatto_sanificazione.ipynb and impatto_conflitti.ipynb so the two
experiments share exactly the same loading, node-availability, CDF and c_wall
verification logic. Nothing here plots; the notebooks own presentation.

Conventions:
  - a "point" is one value of the independent variable (a sanitize interval, or
    a conflict density); each point has several replicas;
  - every results/<scenario>/run_<r>/ holds tasks.csv, nodes.csv, events.csv and
    summary.json; the scenario's config.json holds parameters and conventions.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

CONTROL_PLANE_HINT = "control-plane"


# --------------------------------------------------------------------------- #
# Loading


def load_scenarios(results_root, scenario_dirs, point_key):
    """Load every run of every given scenario into tidy DataFrames.

    Parameters
    ----------
    results_root : path-like
        directory holding results/<scenario>/run_<r>/...
    scenario_dirs : list[str]
        scenario folder names to include (e.g. ["sanitize-1", "sanitize-5"]).
    point_key : str
        name of the scenario param that is the experiment's independent variable
        (e.g. "sanitize_interval_seconds" or "conflict_density"); its value is
        attached to every row as the column ``point``.

    Returns
    -------
    tasks : DataFrame   one row per task, with columns ``point`` and ``replica``
    nodes : DataFrame   one row per node modification, worker nodes only
    runs  : DataFrame   one row per run (params + makespan + run duration)
    """
    results_root = Path(results_root)
    tasks_frames, nodes_frames, run_rows = [], [], []

    for scenario in scenario_dirs:
        scenario_path = results_root / scenario
        run_dirs = sorted(scenario_path.glob("run_*"))
        for run_dir in run_dirs:
            summary = _read_json(run_dir / "summary.json")
            if summary is None:
                continue
            point = summary["params"][point_key]
            replica = summary["replica"]

            t = _read_csv(run_dir / "tasks.csv")
            if t is not None:
                t["point"] = point
                t["replica"] = replica
                t["scenario"] = scenario
                tasks_frames.append(t)

            n = _read_csv(run_dir / "nodes.csv")
            if n is not None:
                n = n[~n["node"].str.contains(CONTROL_PLANE_HINT, na=False)].copy()
                n["point"] = point
                n["replica"] = replica
                n["scenario"] = scenario
                nodes_frames.append(n)

            run_duration = _run_duration(run_dir)
            run_rows.append(
                {
                    "scenario": scenario,
                    "point": point,
                    "replica": replica,
                    "tasks": summary["params"]["tasks"],
                    "sanitize_interval_seconds": summary["params"].get(
                        "sanitize_interval_seconds"
                    ),
                    "conflict_density": summary["params"].get("conflict_density"),
                    "task_duration_seconds": summary["params"].get(
                        "task_duration_seconds"
                    ),
                    "rate_seconds": summary["params"].get("rate_seconds"),
                    "makespan_s": summary.get("makespan_s"),
                    "run_duration_s": run_duration,
                    "blocked": summary["counts"]["blocked"],
                    "submitted": summary["counts"]["submitted"],
                    "timed_out": summary["counts"]["timed_out"],
                }
            )

    tasks = (
        pd.concat(tasks_frames, ignore_index=True) if tasks_frames else pd.DataFrame()
    )
    nodes = (
        pd.concat(nodes_frames, ignore_index=True) if nodes_frames else pd.DataFrame()
    )
    runs = pd.DataFrame(run_rows)
    return tasks, nodes, runs


def _read_json(path):
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else None


def _read_csv(path):
    p = Path(path)
    return pd.read_csv(p) if p.exists() else None


def _run_duration(run_dir):
    """Wall-clock length of the run, from the last event timestamp in events.csv.

    Node availability integrates state up to this instant; without it, the tail
    after the last node change would be uncounted.
    """
    events = _read_csv(Path(run_dir) / "events.csv")
    if events is None or events.empty or "t_recv" not in events:
        return np.nan
    return float(pd.to_numeric(events["t_recv"], errors="coerce").max())


# --------------------------------------------------------------------------- #
# Per-point aggregation (mean of replica-means: measures repeatability)


def per_point_stat(tasks, column, agg="mean"):
    """Aggregate a task column to one value per (point, replica), then summarise
    across replicas.

    Returns a DataFrame indexed by ``point`` with columns ``mean`` and ``std``,
    where the statistics are taken over replicas (each replica contributes its
    own within-run aggregate). This makes error bars reflect run-to-run
    repeatability rather than pooling all tasks together.
    """
    valid = tasks.dropna(subset=[column])
    if valid.empty:
        return pd.DataFrame(columns=["mean", "std"])
    per_replica = valid.groupby(["point", "replica"])[column].agg(agg).reset_index()
    out = per_replica.groupby("point")[column].agg(["mean", "std"]).sort_index()
    out["std"] = out["std"].fillna(0.0)
    return out


def block_fraction_by_cause(tasks):
    """Fraction of tasks per block_cause, per point (mean over replicas).

    Returns a DataFrame indexed by ``point`` with a column per cause
    (none/wall/taint/mixed/other), values in [0, 1].
    """
    per_replica = (
        tasks.groupby(["point", "replica", "block_cause"]).size().reset_index(name="n")
    )
    totals = tasks.groupby(["point", "replica"]).size().reset_index(name="total")
    merged = per_replica.merge(totals, on=["point", "replica"])
    merged["frac"] = merged["n"] / merged["total"]
    pivot = (
        merged.groupby(["point", "block_cause"])["frac"]
        .mean()
        .unstack(fill_value=0.0)
        .sort_index()
    )
    return pivot


# --------------------------------------------------------------------------- #
# Node availability (fraction of time out of N, i.e. sanitizing == True)


def node_unavailability(nodes, runs):
    """Fraction of run time each point's nodes spend out of N (tainted).

    For every (point, replica, node) the sanitizing state is a step function
    defined by nodes.csv modifications; we integrate it from t=0 (nodes start
    clean, guaranteed by clean.py) to the run's end, then average over nodes and
    replicas.

    Returns a DataFrame indexed by ``point`` with columns ``mean`` and ``std``
    (std over replicas).
    """
    if nodes.empty:
        return pd.DataFrame(columns=["mean", "std"])

    run_dur = runs.groupby(["point", "replica"])["run_duration_s"].max().to_dict()

    rows = []
    grouped = nodes.groupby(["point", "replica", "node"])
    for (point, replica, node), g in grouped:
        end = run_dur.get((point, replica))
        if end is None or not np.isfinite(end) or end <= 0:
            continue
        frac = _tainted_fraction(g, end)
        rows.append(
            {"point": point, "replica": replica, "node": node, "tainted_frac": frac}
        )

    per_node = pd.DataFrame(rows)
    if per_node.empty:
        return pd.DataFrame(columns=["mean", "std"])

    per_replica = (
        per_node.groupby(["point", "replica"])["tainted_frac"].mean().reset_index()
    )
    out = per_replica.groupby("point")["tainted_frac"].agg(["mean", "std"]).sort_index()
    out["std"] = out["std"].fillna(0.0)
    return out


def _tainted_fraction(node_events, end_t):
    """Integrate the sanitizing step function for one node over [0, end_t].

    node_events: rows for a single node, with t_recv and sanitizing (bool).
    The node starts not-tainted at t=0; each row sets the state from its t_recv
    onward until the next row (or end_t).
    """
    ev = node_events.sort_values("t_recv")
    times = ev["t_recv"].to_numpy(dtype=float)
    states = ev["sanitizing"].astype(bool).to_numpy()

    tainted = 0.0
    cur_t = 0.0
    cur_state = False  # clean at run start
    for t, s in zip(times, states):
        t = min(t, end_t)
        if t > cur_t and cur_state:
            tainted += t - cur_t
        cur_t = t
        cur_state = s
        if cur_t >= end_t:
            break
    if end_t > cur_t and cur_state:
        tainted += end_t - cur_t
    return tainted / end_t if end_t > 0 else np.nan


# --------------------------------------------------------------------------- #
# Empirical CDF


def ecdf(values):
    """Return (x, y) of the empirical CDF of the given values (NaNs dropped)."""
    v = np.sort(np.asarray([x for x in values if x == x], dtype=float))
    if v.size == 0:
        return np.array([]), np.array([])
    y = np.arange(1, v.size + 1) / v.size
    return v, y


# --------------------------------------------------------------------------- #
# c_wall correctness check (no task bound to a node conflicting with its context)


def load_conflict_pairs(scenario_dir):
    """Read the set of conflicting context pairs from a scenario's seed."""
    seed = _read_json(Path(scenario_dir) / "seed_contexts.json")
    if seed is None:
        return set()
    pairs = set()
    for c in seed.get("conflicts", []):
        a, b = c["context_a"], c["context_b"]
        pairs.add(frozenset((a, b)))
    return pairs


def verify_no_wall_violation(tasks, nodes, scenario_to_dir):
    """Check that no scheduled task landed on a node whose Lambda, at bind time,
    held a context conflicting with the task's context.

    Returns a DataFrame of violations (empty means clean). scenario_to_dir maps
    a scenario name to its scenarios/<name> directory (for the conflict pairs).
    """
    violations = []
    pairs_cache = {}

    scheduled = tasks.dropna(subset=["t_pod_scheduled", "node"])
    for _, task in scheduled.iterrows():
        scenario = task["scenario"]
        if scenario not in pairs_cache:
            pairs_cache[scenario] = load_conflict_pairs(scenario_to_dir[scenario])
        pairs = pairs_cache[scenario]
        if not pairs:
            continue

        lam = _lambda_at(
            nodes,
            scenario,
            task["replica"],
            task["node"],
            float(task["t_pod_scheduled"]),
        )
        ctx = task["context"]
        for other in lam:
            if frozenset((ctx, other)) in pairs:
                violations.append(
                    {
                        "scenario": scenario,
                        "replica": task["replica"],
                        "task_id": task["task_id"],
                        "context": ctx,
                        "node": task["node"],
                        "conflicting_context": other,
                        "t_pod_scheduled": task["t_pod_scheduled"],
                    }
                )
                break
    return pd.DataFrame(violations)


def _lambda_at(nodes, scenario, replica, node, t):
    """Lambda(node) as observed at or just before time t, from nodes.csv."""
    sub = nodes[
        (nodes["scenario"] == scenario)
        & (nodes["replica"] == replica)
        & (nodes["node"] == node)
        & (nodes["t_recv"] <= t)
    ].sort_values("t_recv")
    if sub.empty:
        return []
    raw = sub.iloc[-1]["lambda"]
    try:
        return list(json.loads(raw))
    except (json.JSONDecodeError, TypeError):
        return []


# --------------------------------------------------------------------------- #
# Per-replica aggregation for statistical tests
#
# The replica is the independent experimental unit: each replica contributes one
# aggregate value per point, and the tests compare these across points. Using
# per-task values instead would treat correlated tasks within a run as
# independent and inflate significance, so tests must run on per-replica series.


def per_replica_values(tasks, column, agg="mean"):
    """Map each (point, replica) to one aggregate of `column`.

    Returns a dict {point: [value_per_replica, ...]} with NaNs dropped, ready to
    feed into scipy's non-parametric tests. `agg` is applied within each run
    (e.g. the replica's mean or median latency).
    """
    valid = tasks.dropna(subset=[column])
    per_replica = valid.groupby(["point", "replica"])[column].agg(agg).reset_index()
    out = {}
    for point, g in per_replica.groupby("point"):
        out[point] = g[column].to_numpy(dtype=float).tolist()
    return out
