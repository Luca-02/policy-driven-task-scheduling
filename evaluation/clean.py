"""
clean.py: Reset the cluster to a known-clean state between runs.

Run this BEFORE every run (not only after): the point is to start each run from
a known state, so a leftover from a previous run cannot contaminate the next.

What it does, in order:

  1. delete all TaskRequests in the task namespace (their Jobs and Pods are
     owned via ownerReference and are garbage-collected), then delete any Jobs
     and Pods directly as a safety net, and wait until none remain;
  2. clear every worker's wall memory: remove the Lambda(n) annotation
     (trace.node.<group>/contexts) and the sanitizing taint
     (trace.node.<group>/sanitizing). This is the same end state Sanitize(n)
     reaches, done directly so it does not depend on Pods being gone in a
     particular order or on the sanitize image;
  3. verify the clean state and fail loudly if anything remains;
  4. optionally pause for one sanitize interval to re-align the node-controller
     timer across runs (--settle).

Stale Events are intentionally NOT deleted: deleting them is a slow per-event
API call (hundreds of FailedScheduling events accumulate per conflict run), and
the runner already discards events predating the run start by timestamp. This
saves ~2 minutes per run over a whole sweep.

What it deliberately does NOT do:

  - it does not touch the NodeProperty/GeographicalGroup or the node
    attribute/property labels. Deleting the NodeProperty would make the
    node-controller strip every derived property.* label, which would then need
    a node event to be rewritten. The scenario topology is stable across a
    scenario's replicas and is owned by setup.py, not clean.py.

Names/prefixes come from the scenario's config.json (conventions block) when a
scenario is given, else from defaults matching the deployed system.

Usage:
    python clean.py --scenario scenarios/conflicts-rho020
    python clean.py                      # use defaults, no scenario needed
    python clean.py --settle 30          # also wait 30s to re-align the timer
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------- #
# Conventions / coordinates (defaults match the deployed system).
# Overridable by env; overridden by a scenario's config.json when provided.
# --------------------------------------------------------------------------- #

GROUP_DEFAULT = "policydriven.unimi.it"
TASK_NAMESPACE_DEFAULT = "compute"

# Node-controller trace conventions (from node-controller config).
TRACE_PREFIX_DEFAULT = f"trace.node.{GROUP_DEFAULT}"
CONTEXTS_ANNOTATION_DEFAULT = "contexts"
SANITIZING_TAINT_DEFAULT = "sanitizing"

# Custom resource plurals / kinds.
TASK_REQUESTS_PLURAL = os.getenv("TASK_REQUESTS_PLURAL", "taskrequests")

# Job label linking a Job back to its TaskRequest (task-request-controller).
JOB_LABEL_PREFIX_DEFAULT = "scheduling.task.policydriven.unimi.it"
TASK_REQUEST_REF_LABEL_DEFAULT = "taskRequestRef"

# Polling budget.
DELETE_TIMEOUT = 120


class CleanError(RuntimeError):
    """A cleanup step failed in a way that must abort."""


# --------------------------------------------------------------------------- #
# kubectl helpers.
# --------------------------------------------------------------------------- #


def kubectl(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(["kubectl", *args], capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise CleanError(
            f"kubectl {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}"
        )
    return proc


def kubectl_json(*args: str) -> Any:
    proc = kubectl(*args, "-o", "json")
    return json.loads(proc.stdout)


def log(step: str, message: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {step:<10} {message}", flush=True)


# --------------------------------------------------------------------------- #
# Config resolution.
# --------------------------------------------------------------------------- #


class Conventions:
    """The names clean.py needs, from a scenario config or defaults."""

    def __init__(
        self,
        group: str,
        task_namespace: str,
        nodes: list[str] | None,
    ):
        self.group = group
        self.task_namespace = task_namespace
        self.nodes = nodes  # None => discover all non-control-plane workers
        self.trace_prefix = os.getenv("TRACE_PREFIX", f"trace.node.{group}")
        self.contexts_annotation = os.getenv(
            "CONTEXTS_ANNOTATION", CONTEXTS_ANNOTATION_DEFAULT
        )
        self.sanitizing_taint = os.getenv("SANITIZING_TAINT", SANITIZING_TAINT_DEFAULT)

    @property
    def contexts_annotation_key(self) -> str:
        return f"{self.trace_prefix}/{self.contexts_annotation}"

    @property
    def sanitizing_taint_key(self) -> str:
        return f"{self.trace_prefix}/{self.sanitizing_taint}"


def resolve_conventions(scenario_dir: Path | None) -> Conventions:
    if scenario_dir is not None:
        config = json.loads((scenario_dir / "config.json").read_text())
        conv = config.get("conventions", {})
        group = _group_from_api_version(conv.get("api_version")) or GROUP_DEFAULT
        task_namespace = conv.get("task_namespace", TASK_NAMESPACE_DEFAULT)
        nodes = config.get("scenario", {}).get("nodes")
        return Conventions(group, task_namespace, nodes)
    # Defaults / env only.
    return Conventions(
        group=os.getenv("GROUP", GROUP_DEFAULT),
        task_namespace=os.getenv("TASK_NAMESPACE", TASK_NAMESPACE_DEFAULT),
        nodes=None,
    )


def _group_from_api_version(api_version: str | None) -> str | None:
    if not api_version or "/" not in api_version:
        return None
    return api_version.split("/", 1)[0]


# --------------------------------------------------------------------------- #
# Step 1 — delete TaskRequests / Jobs / Pods and wait.
# --------------------------------------------------------------------------- #


def delete_workloads(conv: Conventions) -> None:
    ns = conv.task_namespace

    log("workloads", f"deleting TaskRequests in namespace {ns!r}")
    kubectl(
        "delete",
        TASK_REQUESTS_PLURAL,
        "--all",
        "-n",
        ns,
        "--ignore-not-found",
        check=False,
    )

    # Safety net: delete Jobs and Pods directly. Owner-reference GC should have
    # handled them, but GC is asynchronous and we want a deterministic wait.
    log("workloads", "deleting Jobs and Pods (safety net)")
    kubectl("delete", "jobs", "--all", "-n", ns, "--ignore-not-found", check=False)
    kubectl(
        "delete",
        "pods",
        "--all",
        "-n",
        ns,
        "--grace-period=0",
        "--force",
        "--ignore-not-found",
        check=False,
    )

    _wait_workloads_gone(conv)
    log("workloads", "no TaskRequests, Jobs or Pods remain")


def _wait_workloads_gone(conv: Conventions) -> None:
    ns = conv.task_namespace
    deadline = time.monotonic() + DELETE_TIMEOUT
    while time.monotonic() < deadline:
        trs = _count(TASK_REQUESTS_PLURAL, ns)
        jobs = _count("jobs", ns)
        pods = _count("pods", ns)
        if trs == 0 and jobs == 0 and pods == 0:
            return
        time.sleep(2)
    raise CleanError(
        f"workloads still present after {DELETE_TIMEOUT}s: "
        f"taskrequests={_count(TASK_REQUESTS_PLURAL, ns)}, "
        f"jobs={_count('jobs', ns)}, pods={_count('pods', ns)}"
    )


def _count(resource: str, namespace: str) -> int:
    proc = kubectl(
        "get",
        resource,
        "-n",
        namespace,
        "-o",
        "jsonpath={.items[*].metadata.name}",
        check=False,
    )
    if proc.returncode != 0:
        return 0
    names = proc.stdout.split()
    return len(names)


# --------------------------------------------------------------------------- #
# Step 2 — clear wall memory (annotation + taint) on every worker.
# --------------------------------------------------------------------------- #


def clear_node_wall_state(conv: Conventions) -> None:
    nodes = conv.nodes if conv.nodes is not None else _discover_workers()
    log("nodes", f"clearing wall memory on {len(nodes)} workers")

    for node in nodes:
        _remove_annotation(node, conv.contexts_annotation_key)
        _remove_taint(node, conv.sanitizing_taint_key)

    log("nodes", "Lambda(n) annotations and sanitizing taints cleared")


def _discover_workers() -> list[str]:
    obj = kubectl_json(
        "get",
        "nodes",
        "-l",
        "!node-role.kubernetes.io/control-plane",
    )
    return [n["metadata"]["name"] for n in obj.get("items", [])]


def _remove_annotation(node: str, key: str) -> None:
    # kubectl annotate node <n> <key>-  removes the annotation if present.
    kubectl("annotate", "node", node, f"{key}-", "--overwrite", check=False)


def _remove_taint(node: str, key: str) -> None:
    # kubectl taint nodes <n> <key>-  removes all taints with that key.
    kubectl("taint", "nodes", node, f"{key}-", check=False)


# --------------------------------------------------------------------------- #
# Step 3 — verify the clean state.
# --------------------------------------------------------------------------- #


def verify_clean(conv: Conventions) -> None:
    ns = conv.task_namespace
    problems: list[str] = []

    trs = _count(TASK_REQUESTS_PLURAL, ns)
    jobs = _count("jobs", ns)
    pods = _count("pods", ns)
    if trs or jobs or pods:
        problems.append(f"workloads remain (tr={trs}, jobs={jobs}, pods={pods})")

    nodes = conv.nodes if conv.nodes is not None else _discover_workers()
    for node in nodes:
        obj = kubectl_json("get", "node", node)
        annotations = obj.get("metadata", {}).get("annotations", {}) or {}
        if conv.contexts_annotation_key in annotations:
            val = annotations[conv.contexts_annotation_key]
            if val not in (None, "", "[]"):
                problems.append(f"{node}: Lambda still set ({val})")
        taints = obj.get("spec", {}).get("taints", []) or []
        if any(t.get("key") == conv.sanitizing_taint_key for t in taints):
            problems.append(f"{node}: sanitizing taint still present")

    if problems:
        raise CleanError("cluster not clean:\n  - " + "\n  - ".join(problems))
    log("verify", "cluster is clean")


# --------------------------------------------------------------------------- #
# Orchestration.                                                               #
# --------------------------------------------------------------------------- #


def run_clean(scenario_dir: Path | None, settle_seconds: int) -> None:
    conv = resolve_conventions(scenario_dir)
    log("start", f"cleaning (namespace={conv.task_namespace})")

    # Order matters: remove workloads first so no active Pod remains, then clear
    # node wall state, then verify. Stale Events are NOT deleted here: deleting
    # them is a slow per-event API call, and the runner already discards events
    # predating the run start by timestamp, so leftovers are harmless. Kubernetes
    # expires events on its own (default --event-ttl 1h).
    delete_workloads(conv)
    clear_node_wall_state(conv)
    verify_clean(conv)

    if settle_seconds > 0:
        log("settle", f"waiting {settle_seconds}s to re-align the sanitize timer")
        time.sleep(settle_seconds)

    log("done", "cluster reset to a clean state")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reset the cluster to a clean state between runs."
    )
    parser.add_argument(
        "--scenario",
        help="path to a scenarios/<name> directory (for its conventions); "
        "optional, defaults are used otherwise",
    )
    parser.add_argument(
        "--settle",
        type=int,
        default=0,
        help="seconds to wait at the end to re-align the node-controller timer "
        "(use the scenario's sanitize interval for consistency across runs)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    scenario_dir = Path(args.scenario) if args.scenario else None
    if scenario_dir is not None and not (scenario_dir / "config.json").exists():
        raise SystemExit(f"error: {scenario_dir}/config.json not found")

    try:
        run_clean(scenario_dir, args.settle)
    except CleanError as e:
        print(f"\nCLEAN FAILED: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
