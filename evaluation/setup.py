"""
setup.py: Apply a generated scenario to a *running* cluster.

Reads a scenario directory produced by generate.py and brings the cluster into
the state that scenario describes, without recreating it. Concretely it:

  1. relabels the worker nodes to the homogeneous evaluation class and waits for
     the node-controller to derive the property.* labels;
  2. applies the evaluation NodeProperty / GeographicalGroup CRs;
  3. wipes and reseeds dataset-service and context-service over a port-forward,
     then verifies the row counts;
  4. sets the runtime knobs on the controllers (sanitize interval, clear-traces
     window, task duration) and waits for the rollouts;
  5. pins the scheduler pod backoff to a constant value (init == max) so retry
     latency during the experiments is not polluted by exponential backoff;
  6. writes setup_applied.json next to the results as a record of what was done.

Everything is idempotent and waits for each change to take effect: a half-applied
configuration would silently corrupt a run.

The cluster is assumed already up (`make init` once). Names/prefixes come from
config.json's "conventions" block, never from defaults here, so setup can never
drift from what generate.py produced.

Usage:
    python setup.py --scenario scenarios/conflicts-rho020 \
        --results results/conflicts-rho020/run_0
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# --------------------------------------------------------------------------- #
# Deployment coordinates (names/namespaces of the deployed system).
# These are cluster facts, not scenario parameters, but are overridable by env
# so a differently-named deployment can still be driven.
# --------------------------------------------------------------------------- #

NODE_CONTROLLER_NS = os.getenv("NODE_CONTROLLER_NAMESPACE", "node-controller")
NODE_CONTROLLER_DEPLOY = os.getenv("NODE_CONTROLLER_DEPLOYMENT", "node-controller")

TRC_NS = os.getenv("TRC_NAMESPACE", "task-request-controller")
TRC_DEPLOY = os.getenv("TRC_DEPLOYMENT", "task-request-controller")

SCHEDULER_NS = os.getenv("SCHEDULER_NAMESPACE", "scheduler")
SCHEDULER_DEPLOY = os.getenv("SCHEDULER_DEPLOYMENT", "scheduler")
SCHEDULER_CONFIGMAP = os.getenv("SCHEDULER_CONFIGMAP", "scheduler-config")
SCHEDULER_CONFIG_KEY = os.getenv("SCHEDULER_CONFIG_KEY", "scheduler-config.yaml")

DATASET_NS = os.getenv("DATASET_SERVICE_NAMESPACE", "dataset-service")
DATASET_SVC = os.getenv("DATASET_SERVICE_NAME", "dataset-service")
CONTEXT_NS = os.getenv("CONTEXT_SERVICE_NAMESPACE", "context-service")
CONTEXT_SVC = os.getenv("CONTEXT_SERVICE_NAME", "context-service")
SERVICE_HTTPS_PORT = int(os.getenv("SERVICE_HTTPS_PORT", "443"))

# Runtime env var names on the controllers (must match the deployments).
ENV_SANITIZE_INTERVAL = "SANITIZE_INTERVAL_SECONDS"
ENV_CLEAR_TRACES = "CLEAR_TRACES_SIMULATION_SECONDS"
ENV_TASK_DURATION = "TASK_SIMULATED_DURATION_SECONDS"
# Optional: TTL after which finished Jobs/Pods are garbage-collected, to keep
# the cluster light on long high-volume runs. Applied only when the scenario
# sets task_ttl_seconds_after_finished; otherwise the controller default (no
# TTL, field omitted) is left untouched.
ENV_TASK_TTL = "TASK_TTL_SECONDS_AFTER_FINISHED"
# The node-controller only registers kopf on.update handlers for nodes and
# node-properties when DEBUG_MODE is true (in production it treats metadata as
# immutable to avoid a TOCTOU race). The evaluation must relabel nodes between
# scenarios, which is an update, so debug mode is required for the derived
# property.* labels to be (re)written.
ENV_DEBUG_MODE = "DEBUG_MODE"

# Polling budgets (seconds).
NODE_LABEL_TIMEOUT = 120
ROLLOUT_TIMEOUT = 180
PORT_FORWARD_TIMEOUT = 30
SERVICE_READY_TIMEOUT = 60


# --------------------------------------------------------------------------- #
# Small kubectl / shell helpers.
# --------------------------------------------------------------------------- #


class SetupError(RuntimeError):
    """A setup step failed in a way that must abort the run."""


def kubectl(
    *args: str, check: bool = True, capture: bool = True
) -> subprocess.CompletedProcess:
    """Run a kubectl command. Raises SetupError on failure when check=True."""
    cmd = ["kubectl", *args]
    proc = subprocess.run(cmd, capture_output=capture, text=True)
    if check and proc.returncode != 0:
        raise SetupError(
            f"kubectl {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}"
        )
    return proc


def kubectl_json(*args: str) -> Any:
    """Run a kubectl command expected to emit JSON and parse it."""
    proc = kubectl(*args, "-o", "json")
    return json.loads(proc.stdout)


def log(step: str, message: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {step:<10} {message}", flush=True)


# --------------------------------------------------------------------------- #
# Scenario loading.
# --------------------------------------------------------------------------- #


@dataclass
class Loaded:
    """The parts of a scenario setup needs, resolved from config.json."""

    root: Path
    config: dict[str, Any]
    conventions: dict[str, Any]
    scenario: dict[str, Any]
    node_labels: dict[str, Any]
    seed_datasets: dict[str, Any]
    seed_contexts: dict[str, Any]


def load_scenario(scenario_dir: Path) -> Loaded:
    config = json.loads((scenario_dir / "config.json").read_text())
    return Loaded(
        root=scenario_dir,
        config=config,
        conventions=config["conventions"],
        scenario=config["scenario"],
        node_labels=json.loads((scenario_dir / "node-labels.json").read_text()),
        seed_datasets=json.loads((scenario_dir / "seed_datasets.json").read_text()),
        seed_contexts=json.loads((scenario_dir / "seed_contexts.json").read_text()),
    )


# --------------------------------------------------------------------------- #
# Step 1 — node labels + property derivation.
# --------------------------------------------------------------------------- #


def apply_node_labels(loaded: Loaded) -> None:
    """Purge stale attribute/property labels and apply the evaluation labels.

    This does NOT wait for the derived property.* labels: the derivation is
    triggered by applying/refreshing the NodeProperty (done next), so waiting
    happens in wait_property_labels() after the manifests are applied.
    """
    nodes: list[str] = loaded.node_labels["nodes"]
    labels: dict[str, str] = loaded.node_labels["labels"]
    purge_prefixes: list[str] = loaded.node_labels["purge_prefixes"]

    log("nodes", f"relabelling {len(nodes)} workers to the evaluation class")
    # Two passes so the attribute change is always an observable transition:
    # purge every node first, then set. If purge and set were interleaved per
    # node, kopf could coalesce the two patches and, seeing the final attributes
    # equal to the pre-existing ones from a previous run, log "attributes
    # unchanged, skipping" and never rewrite the property label.
    for node in nodes:
        _purge_node_labels(node, purge_prefixes)
    pairs = [f"{k}={v}" for k, v in labels.items()]
    for node in nodes:
        kubectl("label", "node", node, *pairs, "--overwrite")


def wait_property_labels(loaded: Loaded) -> None:
    """Wait for the node-controller to derive the property.* labels.

    Called after both the node labels and the NodeProperty manifest are in
    place, so the controller has seen the property it must evaluate against.
    """
    nodes: list[str] = loaded.node_labels["nodes"]
    purge_prefixes: list[str] = loaded.node_labels["purge_prefixes"]
    property_prefix = next(
        (p.rstrip("/") for p in purge_prefixes if p.startswith("property.node.")),
        None,
    )
    if property_prefix is None:
        raise SetupError("node-labels.json has no property.node.* purge prefix")

    _wait_for_property_labels(nodes, property_prefix)
    log("nodes", "all workers carry derived property labels")


def _purge_node_labels(node: str, purge_prefixes: Iterable[str]) -> None:
    """Remove every label on `node` whose key matches one of the prefixes.

    A prefix ending in '/' matches by namespace; a full key (e.g. the topology
    location label) matches exactly.
    """
    node_obj = kubectl_json("get", "node", node)
    existing = node_obj.get("metadata", {}).get("labels", {}) or {}
    to_remove = []
    for key in existing:
        for prefix in purge_prefixes:
            if prefix.endswith("/") and key.startswith(prefix):
                to_remove.append(key)
            elif key == prefix:
                to_remove.append(key)
    for key in to_remove:
        # kubectl label node <n> <key>-   removes the label.
        kubectl("label", "node", node, f"{key}-", check=False)


def _wait_for_property_labels(nodes: list[str], property_prefix: str) -> None:
    """Block until every node has at least one property.<group>/* label."""
    deadline = time.monotonic() + NODE_LABEL_TIMEOUT
    pending = set(nodes)
    while pending and time.monotonic() < deadline:
        for node in list(pending):
            node_obj = kubectl_json("get", "node", node)
            keys = (node_obj.get("metadata", {}).get("labels", {}) or {}).keys()
            if any(k.startswith(f"{property_prefix}/") for k in keys):
                pending.discard(node)
        if pending:
            time.sleep(2)
    if pending:
        raise SetupError(
            f"node-controller did not derive property labels for: {sorted(pending)} "
            f"within {NODE_LABEL_TIMEOUT}s"
        )


# --------------------------------------------------------------------------- #
# Step 2 — CRD manifests (NodeProperty, GeographicalGroup).
# --------------------------------------------------------------------------- #


def delete_existing_crs(loaded: Loaded) -> None:
    """Delete every NodeProperty and GeographicalGroup before applying the
    scenario's own.

    kubectl apply adds/updates but never removes, so a NodeProperty or
    GeographicalGroup left by a previous scenario would survive and pollute the
    evaluation: a stray NodeProperty makes the node-controller write extra
    property.* labels on the nodes, breaking the intended homogeneous class.

    Deleting a NodeProperty makes the controller strip its derived property.*
    label from every node; that is fine here because this runs BEFORE
    apply_manifests + apply_node_labels, which re-apply the scenario property
    and relabel the nodes, rewriting property.<group>/evalprop. --wait makes the
    delete (and the controller's label cleanup it triggers) complete first.
    """
    log("crds", "deleting any existing NodeProperty / GeographicalGroup")
    kubectl(
        "delete",
        "nodeproperties",
        "--all",
        "--wait",
        "--ignore-not-found",
        check=False,
    )
    kubectl(
        "delete",
        "geographicalgroups",
        "--all",
        "--wait",
        "--ignore-not-found",
        check=False,
    )


def apply_manifests(loaded: Loaded) -> None:
    manifests_dir = loaded.root / "manifests"
    log("crds", f"applying manifests from {manifests_dir}")
    kubectl("apply", "-f", str(manifests_dir))


# --------------------------------------------------------------------------- #
# Step 3 — reseed the two microservices over a port-forward.
# --------------------------------------------------------------------------- #


@contextlib.contextmanager
def port_forward(namespace: str, service: str, remote_port: int):
    """Open `kubectl port-forward svc/<service>` on a free local port.

    Yields the local port. TLS is not verified (the services use self-signed
    certs; this mirrors seeding.py's no-CA fallback). NetworkPolicies are not
    enforced under kind's default CNI, so the forward reaches the service.
    """
    local_port = _free_local_port()
    proc = subprocess.Popen(
        [
            "kubectl",
            "port-forward",
            f"svc/{service}",
            f"{local_port}:{remote_port}",
            "-n",
            namespace,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_port_open("127.0.0.1", local_port, PORT_FORWARD_TIMEOUT, proc)
        yield local_port
    finally:
        proc.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=5)
        if proc.poll() is None:
            proc.kill()


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_port_open(host: str, port: int, timeout: int, proc: subprocess.Popen) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            err = proc.stderr.read() if proc.stderr else ""
            raise SetupError(f"port-forward exited early: {err.strip()}")
        with contextlib.suppress(OSError):
            with socket.create_connection((host, port), timeout=1):
                return
        time.sleep(0.3)
    raise SetupError(f"port-forward to {host}:{port} did not open within {timeout}s")


def _unverified_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _http(method: str, url: str, body: Any | None = None) -> tuple[int, str]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(req, context=_unverified_ctx(), timeout=30) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def _wait_service_ready(base: str) -> None:
    """Poll /healthz until the service answers."""
    deadline = time.monotonic() + SERVICE_READY_TIMEOUT
    while time.monotonic() < deadline:
        with contextlib.suppress(Exception):
            status, _ = _http("GET", f"{base}/healthz")
            if status == 200:
                return
        time.sleep(1)
    raise SetupError(f"service at {base} not ready within {SERVICE_READY_TIMEOUT}s")


def reseed_dataset_service(loaded: Loaded) -> None:
    datasets = loaded.seed_datasets["datasets"]
    with port_forward(DATASET_NS, DATASET_SVC, SERVICE_HTTPS_PORT) as port:
        base = f"https://127.0.0.1:{port}"
        _wait_service_ready(base)

        log("datasets", "deleting all existing datasets")
        status, body = _http("DELETE", f"{base}/datasets")
        if status not in (204, 404):
            raise SetupError(f"DELETE /datasets failed: {status} {body}")

        log("datasets", f"seeding {len(datasets)} datasets")
        status, body = _http("POST", f"{base}/datasets/batch", datasets)
        if status != 201:
            raise SetupError(f"POST /datasets/batch failed: {status} {body}")

        # Verify the count.
        status, body = _http("GET", f"{base}/datasets")
        got = len(json.loads(body)) if status == 200 else -1
        if got != len(datasets):
            raise SetupError(
                f"dataset count mismatch after seeding: expected {len(datasets)}, got {got}"
            )
    log("datasets", f"verified {len(datasets)} datasets present")


def reseed_context_service(loaded: Loaded) -> None:
    issuer_auths = loaded.seed_contexts["issuer_auths"]
    conflicts = loaded.seed_contexts["conflicts"]
    with port_forward(CONTEXT_NS, CONTEXT_SVC, SERVICE_HTTPS_PORT) as port:
        base = f"https://127.0.0.1:{port}"
        _wait_service_ready(base)

        # Order matters only in that both are wiped before either is seeded;
        # they are independent tables, so wipe both then seed both.
        log("contexts", "deleting all existing conflicts and issuer-auths")
        for path in ("/conflicts", "/issuer-auths"):
            status, body = _http("DELETE", f"{base}{path}")
            if status not in (204, 404):
                raise SetupError(f"DELETE {path} failed: {status} {body}")

        log("contexts", f"seeding {len(issuer_auths)} issuer-auths")
        status, body = _http("POST", f"{base}/issuer-auths/batch", issuer_auths)
        if status != 201:
            raise SetupError(f"POST /issuer-auths/batch failed: {status} {body}")

        if conflicts:
            log("contexts", f"seeding {len(conflicts)} conflicts")
            status, body = _http("POST", f"{base}/conflicts/batch", conflicts)
            if status != 201:
                raise SetupError(f"POST /conflicts/batch failed: {status} {body}")

        # Verify counts.
        status, body = _http("GET", f"{base}/issuer-auths")
        got_auths = len(json.loads(body)) if status == 200 else -1
        status, body = _http("GET", f"{base}/conflicts")
        got_conflicts = len(json.loads(body)) if status == 200 else -1
        if got_auths != len(issuer_auths):
            raise SetupError(
                f"issuer-auth count mismatch: expected {len(issuer_auths)}, got {got_auths}"
            )
        if got_conflicts != len(conflicts):
            raise SetupError(
                f"conflict count mismatch: expected {len(conflicts)}, got {got_conflicts}"
            )
    log(
        "contexts",
        f"verified {len(issuer_auths)} issuer-auths, {len(conflicts)} conflicts",
    )


# --------------------------------------------------------------------------- #
# Step 4 — runtime knobs on the controllers.
# --------------------------------------------------------------------------- #


def set_controller_env(loaded: Loaded) -> None:
    scenario = loaded.scenario
    sanitize = scenario["sanitize_interval_seconds"]
    clear_traces = scenario["clear_traces_seconds"]
    task_duration = scenario["task_duration_seconds"]

    log(
        "env",
        f"node-controller: {ENV_SANITIZE_INTERVAL}={sanitize} "
        f"{ENV_CLEAR_TRACES}={clear_traces} {ENV_DEBUG_MODE}=true",
    )
    kubectl(
        "set",
        "env",
        "-n",
        NODE_CONTROLLER_NS,
        f"deployment/{NODE_CONTROLLER_DEPLOY}",
        f"{ENV_SANITIZE_INTERVAL}={sanitize}",
        f"{ENV_CLEAR_TRACES}={clear_traces}",
        f"{ENV_DEBUG_MODE}=true",
    )

    trc_env = [f"{ENV_TASK_DURATION}={task_duration}"]
    ttl = scenario.get("task_ttl_seconds_after_finished")
    trc_env.append(f"{ENV_TASK_TTL}={ttl if ttl is not None else ''}")

    log("env", f"task-request-controller: {' '.join(trc_env)}")
    kubectl(
        "set",
        "env",
        "-n",
        TRC_NS,
        f"deployment/{TRC_DEPLOY}",
        *trc_env,
    )

    _rollout_status(NODE_CONTROLLER_NS, NODE_CONTROLLER_DEPLOY)
    _rollout_status(TRC_NS, TRC_DEPLOY)


def _rollout_status(namespace: str, deployment: str) -> None:
    log("rollout", f"waiting for {namespace}/{deployment}")
    kubectl(
        "rollout",
        "status",
        f"deployment/{deployment}",
        "-n",
        namespace,
        f"--timeout={ROLLOUT_TIMEOUT}s",
    )


# --------------------------------------------------------------------------- #
# Step 5 — pin scheduler backoff to a constant.
# --------------------------------------------------------------------------- #


def pin_scheduler_backoff(loaded: Loaded) -> None:
    """Rewrite the scheduler ConfigMap so pod backoff is constant.

    The default is exponential (1s -> 10s); with retries after sanitization,
    that would add a growing, uncontrolled term to the measured wait. Setting
    podInitialBackoffSeconds == podMaxBackoffSeconds makes it constant. The
    value is applied by editing the KubeSchedulerConfiguration YAML held in the
    scheduler-config ConfigMap and restarting the scheduler.
    """
    backoff = loaded.scenario["scheduler_backoff_seconds"]
    log("scheduler", f"pinning pod backoff to {backoff}s (init == max)")

    cm = kubectl_json("get", "configmap", SCHEDULER_CONFIGMAP, "-n", SCHEDULER_NS)
    raw = cm["data"][SCHEDULER_CONFIG_KEY]
    updated = _set_backoff_in_config(raw, backoff)
    if updated == raw:
        log("scheduler", "config already at desired backoff; restarting anyway")

    # Patch the ConfigMap key with the updated document.
    patch = {"data": {SCHEDULER_CONFIG_KEY: updated}}
    kubectl(
        "patch",
        "configmap",
        SCHEDULER_CONFIGMAP,
        "-n",
        SCHEDULER_NS,
        "--type",
        "merge",
        "-p",
        json.dumps(patch),
    )
    # Restart so the scheduler re-reads its mounted config.
    kubectl("rollout", "restart", f"deployment/{SCHEDULER_DEPLOY}", "-n", SCHEDULER_NS)
    _rollout_status(SCHEDULER_NS, SCHEDULER_DEPLOY)


def _set_backoff_in_config(config_yaml: str, backoff: int) -> str:
    """Insert/replace the two backoff fields at the top level of the config.

    The KubeSchedulerConfiguration is a small, flat-topped YAML document; we
    edit it textually to avoid a YAML dependency and to preserve the rest of the
    document (profiles/plugins) byte-for-byte. Both fields are top-level keys.
    """
    lines = config_yaml.splitlines()
    fields = {
        "podInitialBackoffSeconds": backoff,
        "podMaxBackoffSeconds": backoff,
    }
    # Replace existing top-level occurrences.
    for i, line in enumerate(lines):
        stripped = line.strip()
        for key in list(fields):
            if stripped.startswith(f"{key}:") and not line.startswith(" "):
                lines[i] = f"{key}: {fields.pop(key)}"
    # Append any that were missing, before the first list/section if possible.
    # Simplest robust choice: insert right after the apiVersion/kind header,
    # i.e. before the first top-level key that introduces a block ("profiles:").
    if fields:
        insert_at = len(lines)
        for i, line in enumerate(lines):
            if line.startswith("profiles:"):
                insert_at = i
                break
        additions = [f"{k}: {v}" for k, v in fields.items()]
        lines[insert_at:insert_at] = additions
    return "\n".join(lines) + ("\n" if config_yaml.endswith("\n") else "")


# --------------------------------------------------------------------------- #
# Step 6 — record what was applied.
# --------------------------------------------------------------------------- #


def write_applied_record(loaded: Loaded, results_dir: Path) -> None:
    results_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "scenario_name": loaded.scenario["name"],
        "scenario_dir": str(loaded.root),
        "applied": {
            "nodes": loaded.node_labels["nodes"],
            "node_labels": loaded.node_labels["labels"],
            "sanitize_interval_seconds": loaded.scenario["sanitize_interval_seconds"],
            "clear_traces_seconds": loaded.scenario["clear_traces_seconds"],
            "task_duration_seconds": loaded.scenario["task_duration_seconds"],
            "scheduler_backoff_seconds": loaded.scenario["scheduler_backoff_seconds"],
            "datasets": len(loaded.seed_datasets["datasets"]),
            "issuer_auths": len(loaded.seed_contexts["issuer_auths"]),
            "conflicts": len(loaded.seed_contexts["conflicts"]),
        },
        "conventions": loaded.conventions,
    }
    out = results_dir / "setup_applied.json"
    out.write_text(json.dumps(record, indent=2) + "\n")
    log("record", f"wrote {out}")


# --------------------------------------------------------------------------- #
# Orchestration.
# --------------------------------------------------------------------------- #


def run_setup(scenario_dir: Path, results_dir: Path, skip_backoff: bool) -> None:
    loaded = load_scenario(scenario_dir)
    name = loaded.scenario["name"]
    mode = loaded.scenario.get("mode", "system")
    log("start", f"scenario '{name}' (mode={mode})")

    # Step 1: runtime knobs on the controllers FIRST. This also enables
    # DEBUG_MODE on the node-controller and waits for its rollout, so the pod is
    # restarted with the kopf on.update handlers registered BEFORE we touch any
    # node label. Without this, relabelling nodes (an update) would trigger
    # nothing and the derived property.* labels would never be written.
    set_controller_env(loaded)

    # Step 2 & 3: node topology. Delete any pre-existing NodeProperty /
    # GeographicalGroup first (apply does not remove stale ones), then apply the
    # scenario's NodeProperty so the controller knows it, then (re)apply the
    # node attribute labels. apply_node_labels purges the attribute labels
    # before setting them (two passes), so the set is always a real change: the
    # node update event fires and, with the property already known and debug
    # mode on, writes property.<group>/evalprop.
    delete_existing_crs(loaded)
    apply_manifests(loaded)
    apply_node_labels(loaded)
    wait_property_labels(loaded)

    # Step 4: services.
    reseed_dataset_service(loaded)
    reseed_context_service(loaded)

    # Step 5: scheduler backoff. In baseline mode the default scheduler is used
    # and never rejects, so pinning the custom scheduler's backoff is optional;
    # we still pin it so both modes share identical scheduler config.
    if not skip_backoff:
        pin_scheduler_backoff(loaded)
    else:
        log("scheduler", "skipping backoff pin (--skip-backoff)")

    # Step 6: record.
    write_applied_record(loaded, results_dir)
    log("done", f"scenario '{name}' applied")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply a generated scenario to a running cluster."
    )
    parser.add_argument(
        "--scenario", required=True, help="path to a scenarios/<name> directory"
    )
    parser.add_argument(
        "--results",
        help="results directory for setup_applied.json "
        "(default: results/<name>/setup)",
    )
    parser.add_argument(
        "--skip-backoff",
        action="store_true",
        help="do not touch the scheduler backoff config",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    scenario_dir = Path(args.scenario)
    if not (scenario_dir / "config.json").exists():
        raise SystemExit(f"error: {scenario_dir}/config.json not found")

    name = json.loads((scenario_dir / "config.json").read_text())["scenario"]["name"]
    results_dir = (
        Path(args.results) if args.results else Path("results") / name / "setup"
    )

    try:
        run_setup(scenario_dir, results_dir, args.skip_backoff)
    except SetupError as e:
        print(f"\nSETUP FAILED: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
