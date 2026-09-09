"""
scenario.py: load a scenario's conventions and its planned task list.

Conventions come from config.json's "conventions" block so the runner never
drifts from what generate.py produced. Tasks come from tasks.csv (or the
per-replica tasks_r<i>.csv).
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Conventions:
    group: str
    version: str
    task_namespace: str
    tr_plural: str
    trace_prefix: str
    contexts_annotation: str

    @property
    def api_version(self) -> str:
        return f"{self.group}/{self.version}"

    @property
    def contexts_annotation_key(self) -> str:
        return f"{self.trace_prefix}/{self.contexts_annotation}"


def load_conventions(config_json: dict[str, Any]) -> Conventions:
    conv = config_json.get("conventions", {})
    api_version = conv.get("api_version", "policydriven.unimi.it/v1alpha1")
    group, version = api_version.split("/", 1)
    # trace_prefix follows the node-controller convention: trace.node.<group>
    trace_prefix = f"trace.node.{group}"
    return Conventions(
        group=group,
        version=version,
        task_namespace=conv.get("task_namespace", "compute"),
        tr_plural=conv.get("task_requests_plural", "taskrequests"),
        trace_prefix=trace_prefix,
        contexts_annotation="contexts",
    )


@dataclass
class Task:
    """One planned task, from tasks.csv."""

    task_id: int
    name: str
    issuer: str
    context: str
    context_degree: int
    datasets: list[str]
    requirements: dict[str, int]
    geo: str | None
    submit_offset_s: float


def load_tasks(tasks_csv: Path) -> list[Task]:
    tasks: list[Task] = []
    with tasks_csv.open(newline="") as fh:
        for row in csv.DictReader(fh):
            geo = row.get("geo") or None
            tasks.append(
                Task(
                    task_id=int(row["task_id"]),
                    name=row["name"],
                    issuer=row["issuer"],
                    context=row["context"],
                    context_degree=int(row.get("context_degree", 0)),
                    datasets=json.loads(row["datasets"]),
                    requirements=json.loads(row["requirements"]),
                    geo=geo,
                    submit_offset_s=float(row["submit_offset_s"]),
                )
            )
    tasks.sort(key=lambda t: t.submit_offset_s)
    return tasks
