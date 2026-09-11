# Evaluation harness

Reproducible experiments for the policy-driven scheduler. This directory holds
the tooling that generates scenarios, applies them to a **running** cluster,
submits the workload while measuring, and cleans up between runs.

The cluster is assumed to be already up (`make init` once). Nothing here
recreates it: scenarios are applied by relabelling the existing worker nodes and
reseeding the two microservices.

## Components

| Script | Role | Talks to cluster? |
|---|---|---|
| `generate.py` | Emit a self-contained scenario directory (config, seeds, manifests, task plan) | no, files only |
| `setup.py` | Apply a scenario: relabel nodes, reseed services, set runtime knobs | yes |
| `run.py` | Submit tasks, watch resources, write per-task metrics | yes |
| `clean.py` | Reset state between runs (delete tasks/jobs, sanitize nodes, clear events) | yes |
| `analyze.py` | Aggregate runs into figures/tables | no |
| `campaign.py` | Loop scenarios × replicas over setup/clean/run | yes |

`generate.py`, `setup.py`, `clean.py` and `run.py` exist so far.

## `generate.py`

Writes `scenarios/<name>/`:

```
config.json              every parameter + provenance (git sha, timestamp, hashes)
node-labels.json         attribute/topology labels to apply to workers, + prefixes to purge
manifests/
    nodeproperty-evalprop.yaml   single-level property satisfied by all workers
    geo-evalgeo.yaml             single leaf group with the shared location
seed_datasets.json       K datasets, one context each, available on every worker
seed_contexts.json       K issuers (one context each) + the conflict pairs
tasks.csv                ordered submission plan (tasks_r<r>.csv when --replicas > 1)
```

### The scenario model

The evaluation isolates `c_wall`, the only dynamic policy. Every other policy is
made neutral by a **homogeneous** configuration: all workers share one property
class, one location and one leaf geo group, and every dataset is available on
every worker. Under this setup `c_prop`, `c_geo`, `c_static`, `phi_prop` and
`phi_transfer` behave identically on all nodes, so `WallFilter` is the sole
source of scheduling latency beyond a constant baseline. State this explicitly
in the thesis as a deliberate design choice.

Conflicts are parameterised by a **density** `rho` in `[0, 1]`: the fraction of
the `C(K, 2)` possible context pairs declared in conflict. A single seeded
permutation of all pairs is truncated to `ceil(rho * M)`, so:

- scenarios are **nested**: a denser scenario is a superset of a sparser one,
  making the conflict x-axis monotone by construction;
- the conflict graph is a function of the master seed only, so it is **fixed per
  scenario and shared across replicas**. Only the task issuer sequence varies
  with the replica, so replica variability comes from the workload, as intended.

Each task requests one dataset matching one context, so
`auth(iss(t)) = ctx*(t) = {x_k}`: the authorisation perimeter, the deposited
footprint and the task context all coincide, and "number of conflicting pairs"
maps directly onto observable blocking.

### Conventions (environment variables)

The naming conventions the generator must share with the deployed system are
read from the environment, with the same defaults the other components use.
Prefixes are derived from `GROUP` when their own variable is unset (as the
controllers do), but each can be overridden directly.

| Variable | Default | Notes |
|---|---|---|
| `GROUP` | `policydriven.unimi.it` | API group; base for the derived prefixes |
| `VERSION` | `v1alpha1` | CRD version (`API_VERSION = GROUP/VERSION`) |
| `ATTRIBUTE_PREFIX` | `attribute.node.<GROUP>` | node attribute label prefix |
| `PROPERTY_PREFIX` | `property.node.<GROUP>` | derived property label prefix (purged, not written) |
| `NODE_TOPOLOGY_LOCATION_LABEL` | `topology.node.<GROUP>/location` | location label key |
| `TASK_NAMESPACE` | `compute` | namespace of TaskRequests |
| `EVAL_PROPERTY_NAME` | `evalprop` | name of the evaluation NodeProperty |
| `EVAL_GEO_GROUP_NAME` | `evalgeo` | name of the evaluation GeographicalGroup |

These are recorded under `conventions` in every `config.json`, so a scenario
always carries the exact names it was generated with.

### Timing choices

The absolute time values are chosen to keep each run short; the **result does
not depend on them**, only on two ratios:

- `sanitize_interval / rate`: tasks submitted per sanitize window (how fast
  nodes get contaminated);
- `task_duration / sanitize_interval`: how long a node stays occupied
  (deferring sanitization) within a cycle.

Scaling every time by the same factor leaves both ratios unchanged, so the
curves (the knee in `rho`, the U-shape in the interval) are identical while the
wall-clock shrinks. The defaults (`rate = 1s`, `sanitize = 30s`,
`task_duration = 5s`) give **30 tasks per window** and a **1/6** occupancy
ratio, with `N = 100` submitted over ~100s.

Two lower bounds prevent scaling arbitrarily far and should be respected:

- the scheduler pod backoff is fixed at 1s; keep `sanitize_interval` well above
  it (≥ ~5s) so retry latency is dominated by the sanitize wait, not backoff;
- admission + translation cost is a fixed floor of hundreds of ms, so keep
  `rate ≥ ~1s` to avoid submissions overlapping into concurrency noise.

### Reproducibility

- `seed` fixes the conflict graph and the base of the task sequences.
- Replica `r` uses `seed + r` for its task sequence, so **the same replica plays
  the identical task sequence across all scenarios** (paired comparison), while
  differing from the next replica.
- `config.json` records the sha256 of every `tasks.csv`; regenerating with the
  same seed reproduces the same hash.

### Usage

From a YAML scenario file:

```bash
python generate.py --scenario-file scenarios-example/conflicts-rho020.yaml \
    --out scenarios --replicas 5
```

Purely from flags:

```bash
python generate.py --name conflicts-rho020 --seed 10 --contexts 10 \
    --conflict-density 0.20 --tasks 100 --rate-seconds 1 --replicas 5
```

The **conflict sweep** is the same file re-emitted at each density, everything
else fixed:

```bash
for rho in 0 0.05 0.1 0.2 0.3 0.5 1.0; do
  python generate.py --name "conflicts-rho$rho" --seed 10 --contexts 10 \
      --conflict-density "$rho" --tasks 100 --rate-seconds 1 \
      --sanitize-interval-seconds 30 --replicas 5
done
```

The **sanitize sweep** fixes `rho` (a value below the observed knee) and varies
the interval:

```bash
for s in 5 10 20 30 45 60 90 120; do
  python generate.py --name "sanitize-$s" --seed 10 --contexts 10 \
      --conflict-density 0.15 --tasks 100 --rate-seconds 1 \
      --sanitize-interval-seconds "$s" --replicas 5
done
```

The **overhead** experiment reuses the `rho = 0` conflict scenario in two modes:
`--mode system` and `--mode baseline` (plain Jobs on the default scheduler).

### Scenario fields

| Field | Meaning | Used by |
|---|---|---|
| `name` | scenario id (directory name) | all |
| `seed` | master seed (conflict graph + task base) | generate |
| `contexts` | `K`, number of contexts | generate |
| `conflict_density` | `rho` in `[0, 1]` | generate |
| `tasks` | `N`, number of TaskRequests | generate/run |
| `rate_seconds` | inter-arrival time | generate/run |
| `sanitize_interval_seconds` | node-controller timer | setup |
| `clear_traces_seconds` | simulated sanitize work | setup |
| `task_duration_seconds` | `sleep` in each task | setup |
| `scheduler_backoff_seconds` | fixed pod backoff (init == max) | setup |
| `mode` | `system` or `baseline` | run |
| `nodes` | worker node names in the cluster | generate/setup |

`config.json` carries all of these plus derived stats (effective pairs, mean
context degree) so `setup.py`, `run.py` and `analyze.py` never re-take a
parameter by hand.

## `setup.py`

Applies a generated scenario to the **running** cluster (never recreates it):

1. sets the runtime knobs via `kubectl set env` and waits for the rollouts:
   `SANITIZE_INTERVAL_SECONDS`, `CLEAR_TRACES_SIMULATION_SECONDS` **and
   `DEBUG_MODE=true`** on the node-controller, `TASK_SIMULATED_DURATION_SECONDS`
   on the task-request-controller. This is done FIRST: the node-controller only
   registers its kopf `on.update` handlers (for nodes and node-properties) when
   `DEBUG_MODE` is true (in production it treats metadata as immutable) and
   relabelling nodes between scenarios is an update. The pod must be restarted
   with debug mode on before any label is touched, or the derived `property.*`
   labels are never written;
2. applies the evaluation NodeProperty / GeographicalGroup manifests so the
   controller knows the property to evaluate against;
3. purges stale attribute/property/topology labels from each worker (all nodes
   first) and then applies the homogeneous evaluation labels (all nodes), two
   passes so the attribute change is always an observable update that fires the
   node handler, then waits for the derived `property.*` labels (poll with
   timeout);
4. reseeds both microservices over a `kubectl port-forward`: `DELETE` all, then
   `POST /batch`, then a `GET` count check. TLS is not verified (self-signed
   certs, mirroring `seeding.py`'s no-CA fallback); kind's default CNI does not
   enforce the NetworkPolicies, so the forward reaches the services;
5. pins the scheduler pod backoff to a constant by editing
   `podInitialBackoffSeconds == podMaxBackoffSeconds` in the scheduler
   ConfigMap and restarting it, so retry latency is not polluted by exponential
   backoff (`--skip-backoff` to leave it untouched);
6. writes `setup_applied.json` into the results directory as a record.

Every step waits for its effect and fails loudly: a half-applied configuration
would silently corrupt a run. All names/prefixes come from the scenario's
`config.json` (`conventions` block), so setup cannot drift from generate.

Deployment coordinates (namespaces, deployment names, ConfigMap name/key,
service ports) default to the repo's layout and are overridable by environment
variables (`NODE_CONTROLLER_NAMESPACE`, `SCHEDULER_CONFIGMAP`, ... ).

service ports) default to the repo's layout and are overridable by environment
variables (`NODE_CONTROLLER_NAMESPACE`, `SCHEDULER_CONFIGMAP`, ... ).

Setup describes the *scenario*, not a single run: the cluster configuration is
identical across all replicas (only the task sequence in `tasks.csv` differs),
so `setup_applied.json` belongs at the scenario level. The default results path
is `results/<name>/setup`; there is no need to pass `--results` per replica.

```bash
python setup.py --scenario scenarios/conflicts-rho020
# writes results/conflicts-rho020/setup/setup_applied.json
```

## `clean.py`

Resets the cluster to a known-clean state; run it **before every run**, not only
after, so a leftover cannot contaminate the next run:

1. deletes all TaskRequests in the task namespace (Jobs and Pods are owned via
   ownerReference and GC'd), then deletes Jobs and Pods directly as a safety net
   and waits until none remain;
2. clears every worker's wall memory directly: removes the `Lambda(n)`
   annotation (`trace.node.<group>/contexts`) and the sanitizing taint
   (`trace.node.<group>/sanitizing`), the same end state `Sanitize(n)` reaches,
   done directly so it needs no particular Pod ordering and no sanitize image;
3. deletes stale Events in the task namespace so the next run's watch starts
   clean;
4. verifies the clean state and fails loudly if anything remains;
5. with `--settle N`, waits `N`s at the end to re-align the node-controller
   timer across runs.

It deliberately does **not** touch the NodeProperty / GeographicalGroup or the
node labels: deleting the NodeProperty would strip the derived `property.*`
labels, which would then need a node event to be rewritten. That topology is
stable across a scenario's replicas and owned by `setup.py`.

```bash
python clean.py --scenario scenarios/conflicts-rho020 --settle 30
python clean.py            # defaults, no scenario needed
```

## `run.py`

Plays one replica of a scenario against a configured, cleaned cluster and writes
the per-task metrics. Three concurrent roles share one wall clock
(`perf_counter`, ms precision, independent of Kubernetes' second-truncated
timestamps): a **submitter** that creates each TaskRequest at its planned offset
and times the admission round-trip; one **watcher** thread per resource
(TaskRequest, Job, Pod, Event, Node) stamping every event on arrival; a
**recorder** that correlates TaskRequest -> Job -> Pod and fills the records.

Outputs under `results/<name>/run_<replica>/`:
- `tasks.csv` one row per task (submission, admission, translation, scheduling,
  rejections by cause, execution, outcome);
- `events.csv` one row per watch event, appended live (crash-safety net);
- `nodes.csv` taint / `Lambda(n)` timeline per node modification;
- `summary.json` counts, latency/scheduling/admission/translation/wait stats,
  block-cause breakdown, and makespan.

Every knob is a CLI flag defaulting to the scenario value. A `--timeout-seconds`
of `0` means **no global timeout** (the run ends only when every task is
terminal); the default is the submission span plus ten sanitize windows. Use
`--mode baseline` for the overhead baseline (plain Jobs on the default
scheduler, no TaskRequest/Gatekeeper/plugins).

Requires the `kubernetes` Python package (already a project dependency).

`run.py` is a thin CLI entry point; the implementation is split across the
`runner/` package: `util` (pure helpers), `scenario` (conventions + task
loading), `record` (per-task Record and derived columns), `watchers` (one watch
stream per resource), `recorder` (TaskRequest -> Job -> Pod correlation and the
node timeline), `output` (CSV/JSON writers) and `core` (the Runner that
orchestrates submitter, watchers, recorder and outputs).

```bash
python run.py --scenario scenarios/conflicts-rho020 --replica 0
python run.py --scenario scenarios/conflicts-rho020 --replica 0 --timeout-seconds 0
```
