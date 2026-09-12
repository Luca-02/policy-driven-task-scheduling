"""
output.py: write the run's artifacts.

Three CSVs and one JSON. events.csv is opened for streaming append during the
run (a crash-safety net); tasks.csv and nodes.csv are (re)written wholesale on
each flush and at the end; summary.json is computed once at the end from the
finalized records.
"""

from __future__ import annotations

import csv
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .record import Record, TASKS_CSV_FIELDS, WatchEvent
from .utils import get, is_num, percentile

NODES_CSV_FIELDS = ["t_recv", "node", "sanitizing", "lambda_size", "lambda"]
EVENTS_CSV_FIELDS = ["t_recv", "kind", "type", "name", "detail"]


class EventsWriter:
    """Streaming append writer for events.csv."""

    def __init__(self, path: Path):
        self._fh = path.open("w", newline="")
        self._writer = csv.writer(self._fh)
        self._writer.writerow(EVENTS_CSV_FIELDS)

    def append(self, ev: WatchEvent) -> None:
        name = ""
        detail = ""
        if ev.obj is not None:
            name = (
                get(ev.obj, "metadata", "name")
                or get(ev.obj, "involvedObject", "name")
                or ""
            )
            if ev.kind == "Pod":
                detail = (
                    f"phase={get(ev.obj, 'status', 'phase')} "
                    f"node={get(ev.obj, 'spec', 'nodeName')}"
                )
            elif ev.kind == "TaskRequest":
                detail = (
                    f"phase={get(ev.obj, 'status', 'phase')} "
                    f"job={get(ev.obj, 'status', 'jobName')}"
                )
            elif ev.kind == "Event":
                detail = (
                    f"reason={get(ev.obj, 'reason')} "
                    f"count={get(ev.obj, 'count')} "
                    f"msg={(get(ev.obj, 'message') or '')[:500]}"
                )
            elif ev.kind == "Node":
                detail = f"taints={len(get(ev.obj, 'spec', 'taints') or [])}"
        row_t = round(ev.t_recv, 4) if is_num(ev.t_recv) else ev.t_recv
        self._writer.writerow([row_t, ev.kind, ev.type, name, detail])
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


def write_tasks_csv(path: Path, records: dict[int, Record], order: list[int]) -> None:
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=TASKS_CSV_FIELDS)
        writer.writeheader()
        for task_id in order:
            writer.writerow(records[task_id].finalize())


def write_nodes_csv(path: Path, node_rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=NODES_CSV_FIELDS)
        writer.writeheader()
        for row in node_rows:
            writer.writerow(row)


def write_summary(
    path: Path,
    *,
    records: dict[int, Record],
    order: list[int],
    scenario: dict[str, Any],
    replica: int,
    mode: str,
    run_started_epoch: float,
    params: dict[str, Any],
) -> None:
    rows = [records[i].finalize() for i in order]

    def col(name: str) -> list[float]:
        return [r[name] for r in rows if is_num(r[name])]

    def stats(name: str) -> dict[str, float]:
        vals = col(name)
        if not vals:
            return {"n": 0}
        vals_sorted = sorted(vals)
        return {
            "n": len(vals),
            "mean": round(statistics.fmean(vals), 4),
            "median": round(statistics.median(vals), 4),
            "p95": round(percentile(vals_sorted, 95), 4),
            "std": round(statistics.pstdev(vals), 4) if len(vals) > 1 else 0.0,
            "min": round(min(vals), 4),
            "max": round(max(vals), 4),
        }

    submitted = sum(1 for r in rows if is_num(r["t_submit_start"]))
    admitted = sum(1 for r in rows if r["admitted"])
    scheduled = sum(1 for r in rows if is_num(r["t_pod_scheduled"]))
    completed = sum(1 for r in rows if is_num(r["t_pod_succeeded"]))
    timed_out = sum(1 for r in rows if r["timed_out"])
    blocked = sum(1 for r in rows if r["blocked"])

    cause_counts: dict[str, int] = {}
    for r in rows:
        cause_counts[r["block_cause"]] = cause_counts.get(r["block_cause"], 0) + 1

    submit_starts = [r["t_submit_start"] for r in rows if is_num(r["t_submit_start"])]
    succeeded_ts = [r["t_pod_succeeded"] for r in rows if is_num(r["t_pod_succeeded"])]
    makespan = (
        round(max(succeeded_ts) - min(submit_starts), 4)
        if submit_starts and succeeded_ts
        else None
    )

    summary = {
        "scenario": scenario["name"],
        "replica": replica,
        "mode": mode,
        "run_started_epoch": run_started_epoch,
        "run_started_iso": datetime.fromtimestamp(
            run_started_epoch, tz=timezone.utc
        ).isoformat(),
        "params": params,
        "counts": {
            "submitted": submitted,
            "admitted": admitted,
            "scheduled": scheduled,
            "completed": completed,
            "timed_out": timed_out,
            "blocked": blocked,
            "block_cause": cause_counts,
        },
        "latency_s": stats("latency_s"),
        "scheduling_s": stats("scheduling_s"),
        "admission_s": stats("admission_s"),
        "translation_s": stats("translation_s"),
        "pod_creation_s": stats("pod_creation_s"),
        "wait_s": stats("wait_s"),
        "startup_s": stats("startup_s"),
        "execution_s": stats("execution_s"),
        "makespan_s": makespan,
    }
    path.write_text(json.dumps(summary, indent=2) + "\n")
