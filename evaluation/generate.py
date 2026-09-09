"""
generate.py: Scenario generator for the policy-driven scheduler evaluation.

Given a scenario definition (a small YAML file, or command-line flags), this
script produces a self-contained, reproducible scenario directory:

    scenarios/<name>/
        config.json              # every parameter + provenance metadata
        node-labels.json         # attribute/topology labels to apply to workers
        manifests/
            nodeproperty-<p>.yaml # NodeProperty CRs (evaluation property)
            geo-<g>.yaml          # GeographicalGroup CR (single leaf)
        seed_datasets.json       # dataset-service seed (K datasets, 1 context each)
        seed_contexts.json       # context-service seed (issuers + conflict pairs)
        tasks.csv                # the ordered submission plan for the run

Design intent
-------------
The evaluation isolates the only *dynamic* policy of the model, c_wall, by making
every other policy neutral: all workers share one property class, one location and
one leaf geographical group, and every dataset is available on every worker. Under
this homogeneous configuration c_prop / c_geo / c_static / phi_prop / phi_transfer
behave identically on all nodes, so the only plugin that can discriminate between
nodes (and thus the only source of scheduling latency beyond a constant baseline)
is WallFilter.

Conflicts are parameterised by a *conflict density* rho in [0, 1]: the fraction of
the K*(K-1)/2 possible context pairs that are declared in conflict. To keep the
scenarios nested (a denser scenario is a superset of a sparser one) and fully
deterministic, we fix a single seeded permutation of all possible pairs and take
its first ceil(rho * M) elements. The conflict graph is fixed *per scenario* and
shared across replicas; only the task issuer sequence varies with the replica
seed, so replica variability comes from the workload, not from the conflict set.

This script never talks to the cluster. It only writes files. Applying them is
the job of setup.py.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import os
import random
import subprocess
import sys
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------- #
# Conventions (must match the deployed controllers/CRDs).
#
# Configurable via environment variables, with the same defaults the other
# system components use. Prefixes are derived from GROUP when their own
# variable is not set, mirroring how the controllers build them, but each can
# still be overridden directly.
# --------------------------------------------------------------------------- #

GROUP_DEFAULT = "policydriven.unimi.it"
VERSION_DEFAULT = "v1alpha1"
TASK_NAMESPACE_DEFAULT = "compute"
EVAL_PROPERTY_NAME_DEFAULT = "evalprop"
EVAL_GEO_GROUP_NAME_DEFAULT = "evalgeo"

GROUP = os.getenv("GROUP", GROUP_DEFAULT)
VERSION = os.getenv("VERSION", VERSION_DEFAULT)
API_VERSION = f"{GROUP}/{VERSION}"

# Label prefixes read by the node-controller / task-request-controller.
ATTRIBUTE_PREFIX_DEFAULT = f"attribute.node.{GROUP}"
PROPERTY_PREFIX_DEFAULT = f"property.node.{GROUP}"
TOPOLOGY_LOCATION_LABEL_DEFAULT = f"topology.node.{GROUP}/location"

ATTRIBUTE_PREFIX = os.getenv("ATTRIBUTE_PREFIX", ATTRIBUTE_PREFIX_DEFAULT)
PROPERTY_PREFIX = os.getenv("PROPERTY_PREFIX", PROPERTY_PREFIX_DEFAULT)
TOPOLOGY_LOCATION_LABEL = os.getenv(
    "NODE_TOPOLOGY_LOCATION_LABEL", TOPOLOGY_LOCATION_LABEL_DEFAULT
)

# Namespace where TaskRequests live.
TASK_NAMESPACE = os.getenv("TASK_NAMESPACE", TASK_NAMESPACE_DEFAULT)

# Name of the single evaluation NodeProperty and GeographicalGroup.
EVAL_PROPERTY_NAME = os.getenv("EVAL_PROPERTY_NAME", EVAL_PROPERTY_NAME_DEFAULT)
EVAL_GEO_GROUP_NAME = os.getenv("EVAL_GEO_GROUP_NAME", EVAL_GEO_GROUP_NAME_DEFAULT)


# --------------------------------------------------------------------------- #
# Scenario parameters.
# --------------------------------------------------------------------------- #


@dataclass
class Scenario:
    """All the knobs that define one evaluation scenario.

    Only the fields that actually change the generated artifacts live here.
    Cluster-runtime knobs that setup.py applies (sanitize interval, task
    duration, scheduler backoff) are carried through unchanged so that a single
    config.json fully describes a scenario end to end.
    """

    # Identity / reproducibility -------------------------------------------- #
    name: str
    seed: int = 0  # master seed (conflict graph + task sequence base)

    # Cluster shape (homogeneous by construction) --------------------------- #
    # Worker node names as they exist in the running cluster. Defaults to the
    # 5-worker kind cluster from cluster-config.yaml. These are the nodes we
    # relabel and on which every dataset is made available.
    nodes: list[str] = field(
        default_factory=lambda: [
            "kind-worker",
            "kind-worker2",
            "kind-worker3",
            "kind-worker4",
            "kind-worker5"
        ]
    )
    # The single attribute value pair given to every worker. Chosen so the
    # evaluation property resolves to the same level on all of them.
    node_attribute_key: str = "evaltier"
    node_attribute_value: str = "eval"
    node_location: str = "eval-loc"  # single location shared by all workers

    # Contexts / conflicts -------------------------------------------------- #
    contexts: int = 10  # K: number of distinct contexts x_1..x_K
    conflict_density: float = 0.0  # rho in [0, 1]

    # Workload -------------------------------------------------------------- #
    # Timings are scaled to keep wall-clock low without changing the result:
    # the qualitative behaviour depends on the ratios
    #   tasks-per-window = sanitize_interval / rate   (contamination per cycle)
    #   task_duration / sanitize_interval             (node occupancy per cycle)
    # not on the absolute values. Scaling every time by the same factor leaves
    # both ratios (and thus the curves) unchanged while shrinking run duration.
    tasks: int = 100  # N: number of TaskRequests to submit
    rate_seconds: float = 1.0  # inter-arrival time between submissions

    # Runtime knobs carried through to setup.py (not used to build files) --- #
    # sanitize_interval / rate = 30 tasks per sanitize window;
    # task_duration / sanitize_interval = 1/6. backoff stays small vs the
    # interval (~3%), so retry latency is dominated by the sanitize wait.
    sanitize_interval_seconds: int = 30
    clear_traces_seconds: int = 0
    task_duration_seconds: int = 5
    scheduler_backoff_seconds: int = 1

    # Mode: "system" (full pipeline via TaskRequest) or "baseline"
    # (plain Jobs on the default scheduler). Only affects run.py; kept here so
    # the scenario is self-describing.
    mode: str = "system"

    def replica_seed(self, replica: int) -> int:
        """Seed for the task issuer sequence of a given replica.

        The conflict graph always uses the master seed; the task sequence uses
        seed + replica, so replica r plays the *same* task sequence across all
        scenarios (paired comparison) while each replica differs from the next.
        """
        return self.seed + replica


# --------------------------------------------------------------------------- #
# Conflict-graph construction.
# --------------------------------------------------------------------------- #


def context_names(k: int) -> list[str]:
    """Return the K context names x1..xK (1-based, zero-padded for sorting)."""
    width = len(str(k))
    return [f"x{str(i).zfill(width)}" for i in range(1, k + 1)]


def conflict_pairs(contexts: list[str], rho: float, seed: int) -> list[tuple[str, str]]:
    """Deterministically select ceil(rho * M) conflict pairs.

    A single seeded permutation of all M = C(K, 2) unordered pairs is drawn, and
    its first ceil(rho * M) elements are returned. Because the permutation is a
    function of the seed only (not of rho), the pair set for a larger rho is a
    strict superset of the pair set for a smaller rho: scenarios are nested and
    the x-axis of the conflict experiment is monotone by construction.
    """
    if not (0.0 <= rho <= 1.0):
        raise ValueError(f"conflict_density must be in [0, 1], got {rho}")

    all_pairs = list(itertools.combinations(contexts, 2))
    rng = random.Random(seed)
    rng.shuffle(all_pairs)  # in-place, deterministic given seed

    count = math.ceil(rho * len(all_pairs))
    return all_pairs[:count]


def context_degrees(
    contexts: list[str], pairs: list[tuple[str, str]]
) -> dict[str, int]:
    """Number of conflict neighbours of each context in the conflict graph."""
    degree = {c: 0 for c in contexts}
    for a, b in pairs:
        degree[a] += 1
        degree[b] += 1
    return degree


# --------------------------------------------------------------------------- #
# Seed files for the two microservices.
# --------------------------------------------------------------------------- #


def build_dataset_seed(scenario: Scenario, contexts: list[str]) -> dict[str, Any]:
    """One dataset d_k per context x_k, homogeneous across nodes.

    Every dataset carries exactly one context, is available on every worker, has
    the same requirements and the same geo (the single leaf group). This makes
    c_static / phi_transfer identical on all admissible nodes, leaving c_wall as
    the sole discriminator.

    beta(d) is expressed over the properties that actually exist in the cluster.
    The only property here is the evaluation property, requested at level 1,
    matching the task's own requirement so that beta*(t) = max over task and
    datasets stays at level 1 and is satisfied by every worker.
    """
    datasets = []
    for i, ctx in enumerate(contexts, start=1):
        datasets.append(
            {
                "name": f"d{str(i).zfill(len(str(len(contexts))))}",
                "requirements": {EVAL_PROPERTY_NAME: 1},
                "size_mb": 1024,
                "nodes": list(scenario.nodes),  # available everywhere
                "geo": EVAL_GEO_GROUP_NAME,
                "static": False,
                "contexts": [ctx],  # single-context dataset
            }
        )
    return {"datasets": datasets}


def build_context_seed(
    scenario: Scenario, contexts: list[str], pairs: list[tuple[str, str]]
) -> dict[str, Any]:
    """One issuer i_k authorised on exactly one context x_k, plus the conflicts.

    With auth(i_k) = {x_k} and req(task_k) = {d_k} (ctx*(task_k) = {x_k}), the
    authorisation perimeter, the deposited footprint and the task context all
    coincide, so "number of conflicting pairs" maps directly onto observable
    blocking behaviour.
    """
    issuer_auths = [
        {"name": issuer_name(i), "contexts": [ctx]}
        for i, ctx in enumerate(contexts, start=1)
    ]
    conflicts = [{"context_a": a, "context_b": b} for a, b in pairs]
    return {"conflicts": conflicts, "issuer_auths": issuer_auths}


def issuer_name(index: int) -> str:
    """Issuer name for context index (1-based)."""
    return f"issuer{index}"


# --------------------------------------------------------------------------- #
# CRD manifests (NodeProperty, GeographicalGroup).
# --------------------------------------------------------------------------- #


def build_nodeproperty_manifest(scenario: Scenario) -> str:
    """A single-level NodeProperty satisfied by every worker.

    Level 1 is: <attribute_key> Eq <attribute_value>. Since every worker gets
    that attribute label in setup.py, every worker resolves to level 1, so the
    property never excludes a node and phi_prop is constant. We still define a
    real property (rather than none) so the full labelling / evaluation path of
    the node-controller is exercised, keeping the pipeline realistic.
    """
    manifest = {
        "apiVersion": API_VERSION,
        "kind": "NodeProperty",
        "metadata": {"name": EVAL_PROPERTY_NAME},
        "spec": {
            "levels": [
                {
                    "disjunction": [
                        {
                            "clause": [
                                {
                                    "key": scenario.node_attribute_key,
                                    "operator": "Eq",
                                    "values": [scenario.node_attribute_value],
                                }
                            ]
                        }
                    ]
                }
            ]
        },
    }
    return to_yaml(manifest)


def build_geo_manifest(scenario: Scenario) -> str:
    """A single leaf GeographicalGroup containing only the shared location."""
    manifest = {
        "apiVersion": API_VERSION,
        "kind": "GeographicalGroup",
        "metadata": {"name": EVAL_GEO_GROUP_NAME},
        "spec": {"locations": [scenario.node_location]},
    }
    return to_yaml(manifest)


# --------------------------------------------------------------------------- #
# Node labels (applied by setup.py, not here).
# --------------------------------------------------------------------------- #


def build_node_labels(scenario: Scenario) -> dict[str, Any]:
    """The attribute/topology labels every worker must carry.

    Property labels (property.node.*) are intentionally NOT listed: they are
    derived and written by the node-controller from these attribute labels.
    setup.py applies the "set" labels and strips any stale attribute/property
    label outside this set before the run.
    """
    attr_label = f"{ATTRIBUTE_PREFIX}/{scenario.node_attribute_key}"
    return {
        "nodes": list(scenario.nodes),
        "labels": {
            attr_label: scenario.node_attribute_value,
            TOPOLOGY_LOCATION_LABEL: scenario.node_location,
        },
        # Prefixes setup.py should purge on the workers before applying the
        # labels above, so no leftover attribute/property from a previous
        # scenario survives.
        "purge_prefixes": [
            f"{ATTRIBUTE_PREFIX}/",
            f"{PROPERTY_PREFIX}/",
            TOPOLOGY_LOCATION_LABEL,
        ],
    }


# --------------------------------------------------------------------------- #
# Task submission plan.
# --------------------------------------------------------------------------- #


def build_tasks(
    scenario: Scenario, contexts: list[str], degrees: dict[str, int], replica: int
) -> list[dict[str, Any]]:
    """Generate the ordered list of tasks for one replica.

    Each task picks a context uniformly at random (seeded per replica), and is
    issued by the corresponding issuer requesting the corresponding dataset.
    submit_offset_s is the planned submission instant relative to run start, so
    run.py performs no scheduling logic of its own: it just waits and submits.
    """
    rng = random.Random(scenario.replica_seed(replica))
    width = len(str(scenario.tasks))
    rows: list[dict[str, Any]] = []

    for i in range(scenario.tasks):
        ctx_index = rng.randrange(len(contexts))  # 0-based
        ctx = contexts[ctx_index]
        human_index = ctx_index + 1
        task_id = i
        name = f"eval-{scenario.name}-r{replica}-{str(i).zfill(width)}"
        rows.append(
            {
                "task_id": task_id,
                "name": name,
                "issuer": issuer_name(human_index),
                "context": ctx,
                "context_degree": degrees[ctx],
                # req(t) = {d_k}: single dataset matching the context.
                "datasets": json.dumps(
                    [f"d{str(human_index).zfill(len(str(len(contexts))))}"]
                ),
                # beta(t): request level 1 of the evaluation property, met by all.
                "requirements": json.dumps({EVAL_PROPERTY_NAME: 1}),
                "geo": EVAL_GEO_GROUP_NAME,
                "submit_offset_s": round(i * scenario.rate_seconds, 3),
            }
        )
    return rows


TASKS_CSV_FIELDS = [
    "task_id",
    "name",
    "issuer",
    "context",
    "context_degree",
    "datasets",
    "requirements",
    "geo",
    "submit_offset_s",
]


def write_tasks_csv(path: Path, rows: list[dict[str, Any]]) -> str:
    """Write tasks.csv and return its sha256 (recorded in config for integrity)."""
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=TASKS_CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return sha256_of(path)


# --------------------------------------------------------------------------- #
# Minimal YAML emitter (avoids a PyYAML dependency for the few docs we write).
# --------------------------------------------------------------------------- #


def to_yaml(obj: Any, indent: int = 0) -> str:
    """Emit a small, well-formed YAML document for dict/list/scalar trees.

    Deliberately tiny: it only needs to serialise the CRD manifests we build
    above, whose shapes are known. It quotes strings that need quoting and
    renders ints/floats/bools natively.
    """
    pad = "  " * indent
    lines: list[str] = []

    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, (dict, list)):
                lines.append(f"{pad}{key}:")
                lines.append(to_yaml(value, indent + 1))
            else:
                lines.append(f"{pad}{key}: {scalar(value)}")
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict):
                # Render first key on the dash line, the rest indented.
                inner = to_yaml(item, indent + 1)
                inner_lines = inner.split("\n")
                first = inner_lines[0].lstrip()
                lines.append(f"{pad}- {first}")
                for extra in inner_lines[1:]:
                    lines.append(extra)
            elif isinstance(item, list):
                lines.append(f"{pad}-")
                lines.append(to_yaml(item, indent + 1))
            else:
                lines.append(f"{pad}- {scalar(item)}")
    else:
        return f"{pad}{scalar(obj)}"

    return "\n".join(line for line in lines if line != "")


def scalar(value: Any) -> str:
    """Render a scalar for YAML, quoting strings when necessary."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if (
        text == ""
        or any(ch in text for ch in ":#{}[],&*!|>'\"%@`")
        or text != text.strip()
    ):
        escaped = text.replace('"', '\\"')
        return f'"{escaped}"'
    return text


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def git_revision() -> str | None:
    """Best-effort short git SHA of the repository, for provenance."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return None


def load_scenario_yaml(path: Path) -> dict[str, Any]:
    """Load a scenario YAML file using PyYAML if available, else a tiny parser.

    The scenario file is intentionally flat (key: value, and simple lists), so a
    minimal fallback parser covers it when PyYAML is not installed.
    """
    text = path.read_text()
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text) or {}
    except ImportError:
        return _parse_flat_yaml(text)


def _parse_flat_yaml(text: str) -> dict[str, Any]:
    """Fallback parser for a flat scenario file (scalars and inline lists)."""
    result: dict[str, Any] = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value == "":
            continue
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            items = [v.strip().strip("'\"") for v in inner.split(",") if v.strip()]
            result[key] = items
        else:
            result[key] = _coerce_scalar(value.strip("'\""))
    return result


def _coerce_scalar(value: str) -> Any:
    for caster in (int, float):
        try:
            return caster(value)
        except ValueError:
            continue
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    return value


# --------------------------------------------------------------------------- #
# Orchestration.
# --------------------------------------------------------------------------- #


def generate(scenario: Scenario, out_root: Path, replicas: int) -> Path:
    """Write the full scenario directory and return its path."""
    scenario_dir = out_root / scenario.name
    manifests_dir = scenario_dir / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)

    contexts = context_names(scenario.contexts)
    pairs = conflict_pairs(contexts, scenario.conflict_density, scenario.seed)
    degrees = context_degrees(contexts, pairs)

    # Seed files for the two services.
    (scenario_dir / "seed_datasets.json").write_text(
        json.dumps(build_dataset_seed(scenario, contexts), indent=2) + "\n"
    )
    (scenario_dir / "seed_contexts.json").write_text(
        json.dumps(build_context_seed(scenario, contexts, pairs), indent=2) + "\n"
    )

    # CRD manifests.
    (manifests_dir / f"nodeproperty-{EVAL_PROPERTY_NAME}.yaml").write_text(
        build_nodeproperty_manifest(scenario) + "\n"
    )
    (manifests_dir / f"geo-{EVAL_GEO_GROUP_NAME}.yaml").write_text(
        build_geo_manifest(scenario) + "\n"
    )

    # Node labels descriptor.
    (scenario_dir / "node-labels.json").write_text(
        json.dumps(build_node_labels(scenario), indent=2) + "\n"
    )

    # Per-replica task plans, plus integrity hashes.
    task_hashes: dict[str, str] = {}
    for replica in range(replicas):
        rows = build_tasks(scenario, contexts, degrees, replica)
        tasks_path = scenario_dir / (
            "tasks.csv" if replicas == 1 else f"tasks_r{replica}.csv"
        )
        task_hashes[tasks_path.name] = write_tasks_csv(tasks_path, rows)

    # Effective conflict stats for the record and for the scenario table.
    effective_pairs = len(pairs)
    max_pairs = len(contexts) * (len(contexts) - 1) // 2
    mean_degree = (2 * effective_pairs / len(contexts)) if contexts else 0.0

    config = {
        "scenario": asdict(scenario),
        "derived": {
            "contexts": contexts,
            "conflict_pairs_effective": effective_pairs,
            "conflict_pairs_max": max_pairs,
            "conflict_density_effective": (
                round(effective_pairs / max_pairs, 4) if max_pairs else 0.0
            ),
            "mean_context_degree": round(mean_degree, 4),
            "replicas": replicas,
        },
        "conventions": {
            "api_version": API_VERSION,
            "attribute_prefix": ATTRIBUTE_PREFIX,
            "topology_location_label": TOPOLOGY_LOCATION_LABEL,
            "task_namespace": TASK_NAMESPACE,
            "eval_property_name": EVAL_PROPERTY_NAME,
            "eval_geo_group_name": EVAL_GEO_GROUP_NAME,
        },
        "integrity": {"tasks_sha256": task_hashes},
        "provenance": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "git_revision": git_revision(),
            "generator": "generate.py",
        },
    }
    (scenario_dir / "config.json").write_text(json.dumps(config, indent=2) + "\n")

    return scenario_dir


def scenario_from_args(args: argparse.Namespace) -> Scenario:
    """Build a Scenario from a YAML file (if given) overlaid with CLI flags."""
    data: dict[str, Any] = {}
    if args.scenario_file:
        data.update(load_scenario_yaml(Path(args.scenario_file)))

    # CLI flags override file values when explicitly provided.
    overrides = {
        "name": args.name,
        "seed": args.seed,
        "contexts": args.contexts,
        "conflict_density": args.conflict_density,
        "tasks": args.tasks,
        "rate_seconds": args.rate_seconds,
        "sanitize_interval_seconds": args.sanitize_interval_seconds,
        "clear_traces_seconds": args.clear_traces_seconds,
        "task_duration_seconds": args.task_duration_seconds,
        "scheduler_backoff_seconds": args.scheduler_backoff_seconds,
        "mode": args.mode,
    }
    for key, value in overrides.items():
        if value is not None:
            data[key] = value
    if args.nodes:
        data["nodes"] = args.nodes

    if "name" not in data:
        raise SystemExit("error: scenario 'name' is required (flag --name or in file)")

    valid = {f for f in Scenario.__dataclass_fields__}  # type: ignore[attr-defined]
    unknown = set(data) - valid
    if unknown:
        raise SystemExit(f"error: unknown scenario keys: {sorted(unknown)}")

    return Scenario(**data)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a reproducible evaluation scenario (files only)."
    )
    parser.add_argument("--scenario-file", help="YAML scenario definition")
    parser.add_argument("--out", default="scenarios", help="output root directory")
    parser.add_argument(
        "--replicas",
        type=int,
        default=1,
        help="number of per-replica task plans to emit (default 1)",
    )

    parser.add_argument("--name")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--contexts", type=int)
    parser.add_argument("--conflict-density", type=float, dest="conflict_density")
    parser.add_argument("--tasks", type=int)
    parser.add_argument("--rate-seconds", type=float, dest="rate_seconds")
    parser.add_argument(
        "--sanitize-interval-seconds", type=int, dest="sanitize_interval_seconds"
    )
    parser.add_argument("--clear-traces-seconds", type=int, dest="clear_traces_seconds")
    parser.add_argument(
        "--task-duration-seconds", type=int, dest="task_duration_seconds"
    )
    parser.add_argument(
        "--scheduler-backoff-seconds", type=int, dest="scheduler_backoff_seconds"
    )
    parser.add_argument("--mode", choices=["system", "baseline"])
    parser.add_argument(
        "--nodes", nargs="+", help="worker node names (space separated)"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    scenario = scenario_from_args(args)
    scenario_dir = generate(scenario, Path(args.out), args.replicas)

    config = json.loads((scenario_dir / "config.json").read_text())
    derived = config["derived"]
    print(f"scenario written to: {scenario_dir}")
    print(
        f"  contexts K            = {scenario.contexts}\n"
        f"  conflict density rho  = {scenario.conflict_density} "
        f"(effective {derived['conflict_density_effective']})\n"
        f"  conflict pairs        = {derived['conflict_pairs_effective']} "
        f"/ {derived['conflict_pairs_max']}\n"
        f"  mean context degree   = {derived['mean_context_degree']}\n"
        f"  tasks N               = {scenario.tasks} @ {scenario.rate_seconds}s\n"
        f"  replicas              = {derived['replicas']}\n"
        f"  mode                  = {scenario.mode}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
