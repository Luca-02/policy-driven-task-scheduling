# Evaluation

Tooling for the experimental evaluation presented in the thesis. It generates
reproducible scenarios, applies them to a **running** cluster, submits the
workload while measuring every step, and analyses the results.

The cluster is assumed to be already up (`make init`, once). Nothing here
recreates it: a scenario is applied by relabelling the existing worker nodes
and reseeding the two services.

## What is measured

The evaluation isolates `c_wall`, the only policy whose outcome depends on the
history of the cluster. Two factors drive its behaviour, and each experiment
varies one of them while the other stays fixed.

| Experiment | Independent variable | Fixed | Notebook |
| --- | --- | --- | --- |
| Impact of conflicts | conflict density `ρ` | sanitization interval `τ` | `impatto_conflitti.ipynb` |
| Impact of sanitization | sanitization interval `τ` | conflict density `ρ` | `impatto_sanificazione.ipynb` |

The main metric is the **scheduling latency** of each task, from the
submission of the `TaskRequest` to the binding of its Pod. It is complemented
by the fraction of blocked tasks and the cause of the block, the waiting time
of blocked tasks, the unavailability of the nodes and the makespan.

### The scenario model

Every other policy is made neutral by a **homogeneous** configuration: all
workers share one property class, one location and one leaf geographical
group, and every dataset is available on every worker. Under this setup
`c_prop`, `c_geo`, `c_static`, `φ_prop` and `φ_transfer` behave identically on
all nodes, so `WallFilter` is the only source of scheduling latency beyond a
constant baseline. This mirrors the point of the pipeline where `c_wall`
actually operates: the static policies have already narrowed the candidates
to a set that is homogeneous with respect to them.

A scenario defines `K` contexts and, for each one, a dataset that belongs to
that context only and an issuer authorized on that context only. Each task
requests the single dataset of its issuer's context, so
`auth(iss(t)) = ctx*(t) = {x_k}`: the authorization perimeter, the deposited
footprint and the task context coincide, and the number of conflicting pairs
maps directly onto observable blocking.

Conflicts are parameterised by a **density** `ρ` in `[0, 1]`, the fraction of
the `C(K, 2)` possible context pairs declared in conflict. A single seeded
permutation of all pairs is truncated to `ceil(ρ · C(K, 2))`, therefore:

- scenarios are **nested**: a denser scenario is a superset of a sparser one,
  which makes the conflict axis monotone by construction;
- the conflict graph depends on the master seed only, so it is fixed per
  scenario and shared by all its replicas. Only the sequence of task issuers
  varies with the replica.

## Layout

| Path | Role | Talks to the cluster |
| --- | --- | --- |
| `generate.py` | writes a self-contained scenario directory | no |
| `setup.py` | applies a scenario: runtime knobs, node labels, seed data | yes |
| `clean.py` | resets the state between runs | yes |
| `run.py` | submits the tasks, watches the cluster, writes the metrics | yes |
| `runner/` | implementation behind `run.py` | yes |
| `experiments/` | the two sweeps, chaining the four scripts above | yes |
| `analysis/utils.py` | loading and aggregation helpers used by the notebooks | no |
| `impatto_conflitti.ipynb`, `impatto_sanificazione.ipynb` | analysis, figures and statistical tests | no |
| `scenarios/` | generated scenarios | |
| `results/` | raw measurements, one directory per scenario and replica | |
| `analysis/figures/`, `analysis/tables/` | figures and LaTeX tables produced by the notebooks | |

## Requirements

- Python 3.12 with the `kubernetes` package for the scripts, plus `pyyaml`
  only if scenarios are read from a YAML file; `numpy`, `pandas`, `scipy`,
  `matplotlib` and Jupyter for the notebooks.
- `kubectl` pointing at an initialized cluster.
- The worker nodes named in the scenario must exist. The defaults match the
  five workers created by `make init`.

All the commands below are meant to be run from this directory.

## Reproducing the experiments

The two sweeps regenerate the scenarios, configure the cluster and run every
replica. The values below are those used in the thesis.

```bash
# Impact of conflicts: ρ from 0.1 to 0.8, τ = 20 s
TASKS=200 INTERVAL=20 TASK_DURATION=20 REPLICAS=5 \
DENSITIES="0.1 0.2 0.3 0.4 0.5 0.6 0.7 0.8" \
bash experiments/conflicts_sweep.sh

# Impact of sanitization: τ from 1 s to 50 s, ρ = 0.5
TASKS=200 DENSITY=0.5 TASK_DURATION=20 REPLICAS=5 \
INTERVALS="1 3 5 10 20 30 40 50" \
bash experiments/sanitize_sweep.sh
```

| Variable | Meaning |
| --- | --- |
| `SEED` | master seed, 42 by default |
| `CONTEXTS` | number of contexts `K`, 10 by default |
| `TASKS` | tasks per run `N` |
| `RATE` | seconds between two submissions, 1 by default |
| `TASK_DURATION` | simulated duration of a task, in seconds |
| `REPLICAS` | replicas per scenario |
| `NODES` | worker node names, space separated |
| `TASK_TTL` | if set, finished Jobs are removed after this many seconds |
| `DENSITIES` / `INTERVAL` | grid of `ρ` and fixed `τ`, conflicts sweep |
| `INTERVALS` / `DENSITY` | grid of `τ` and fixed `ρ`, sanitization sweep |

Each sweep starts by pre-pulling the task image on every node through a
short-lived DaemonSet, so the first scenario is not penalised by a cold image
cache. For every point of the grid it then runs `generate.py`, `setup.py` once,
and `clean.py` followed by `run.py` for each replica.

A full sweep takes a few hours. Once it has finished, open the corresponding
notebook and run all the cells to rebuild figures, tables and statistical
tests from `results/`.

## The scripts in detail

### `generate.py`

Writes `scenarios/<name>/`:

```
config.json              every parameter plus provenance (git sha, timestamp, hashes)
node-labels.json         attribute and topology labels for the workers, and the prefixes to purge
manifests/
    nodeproperty-evalprop.yaml   single-level property satisfied by all workers
    geo-evalgeo.yaml             single leaf group with the shared location
seed_datasets.json       K datasets, one context each, available on every worker
seed_contexts.json       K issuers, one context each, and the conflict pairs
tasks_r<r>.csv           ordered submission plan of replica r (tasks.csv with a single replica)
```

```bash
# From flags
python generate.py --name conflicts-rho020 --seed 42 --contexts 10 \
    --conflict-density 0.20 --tasks 200 --rate-seconds 1 \
    --sanitize-interval-seconds 20 --task-duration-seconds 20 --replicas 5

# From a YAML file; any field can still be overridden on the command line
python generate.py --scenario-file scenarios/conflicts-rho020.yaml --replicas 5
```

| Field | Meaning | Used by |
| --- | --- | --- |
| `name` | scenario id and directory name | all |
| `seed` | master seed: conflict graph and base of the task sequences | generate |
| `contexts` | `K`, number of contexts | generate |
| `conflict_density` | `ρ` in `[0, 1]` | generate |
| `tasks` | `N`, number of tasks | generate, run |
| `rate_seconds` | time between two submissions | generate, run |
| `sanitize_interval_seconds` | `τ`, period of the node-controller timer | setup |
| `clear_traces_seconds` | simulated duration of the trace removal | setup |
| `task_duration_seconds` | simulated duration of each task | setup |
| `task_ttl_seconds` | time after which finished Jobs are removed | setup |
| `scheduler_backoff_seconds` | fixed Pod backoff of the scheduler | setup |
| `mode` | `system` or `baseline` | run |
| `nodes` | worker node names in the cluster | generate, setup |

`config.json` carries all of these plus derived statistics, such as the
effective number of pairs and the mean context degree, so the other scripts
never take a parameter by hand.

**Reproducibility.** The seed fixes the conflict graph. Replica `r` uses
`seed + r` for its task sequence, so the same replica plays the identical
sequence of tasks in every scenario, which makes the comparison paired, while
differing from the other replicas. `config.json` records the SHA-256 of every
task file: regenerating with the same seed reproduces the same hashes.

**Naming conventions.** The names shared with the deployed system are read
from the environment, with the same defaults as the other components, and
recorded under `conventions` in `config.json`.

| Variable | Default | Notes |
| --- | --- | --- |
| `GROUP` | `policydriven.unimi.it` | API group, base of the derived prefixes |
| `VERSION` | `v1alpha1` | version of the custom resources |
| `ATTRIBUTE_PREFIX` | `attribute.node.<GROUP>` | prefix of the node attribute labels |
| `PROPERTY_PREFIX` | `property.node.<GROUP>` | prefix of the derived property labels, purged but never written |
| `NODE_TOPOLOGY_LOCATION_LABEL` | `topology.node.<GROUP>/location` | location label |
| `TASK_NAMESPACE` | `compute` | namespace of the tasks |
| `EVAL_PROPERTY_NAME` | `evalprop` | name of the evaluation `NodeProperty` |
| `EVAL_GEO_GROUP_NAME` | `evalgeo` | name of the evaluation `GeographicalGroup` |

### `setup.py`

Applies a generated scenario to the running cluster. Every step waits for its
effect and fails loudly, because a half-applied configuration would silently
corrupt a run.

1. Sets the runtime knobs with `kubectl set env` and waits for the rollouts:
   `SANITIZE_INTERVAL_SECONDS`, `CLEAR_TRACES_SIMULATION_SECONDS` and
   `DEBUG_MODE=true` on the node-controller,
   `TASK_SIMULATED_DURATION_SECONDS` and `TASK_TTL_SECONDS_AFTER_FINISHED`
   on the task-request-controller. This
   comes first on purpose: the node-controller reacts to node updates only in
   debug mode, and relabelling the nodes between scenarios is an update.
2. Applies the evaluation `NodeProperty` and `GeographicalGroup`.
3. Purges the stale attribute, property and topology labels from every worker,
   then applies the homogeneous evaluation labels and waits for the derived
   property labels to appear.
4. Reseeds both services through a `kubectl port-forward`: delete everything,
   post the batch, check the count.
5. Pins the Pod backoff of the scheduler to a constant, by setting
   `podInitialBackoffSeconds` equal to `podMaxBackoffSeconds` in the scheduler
   ConfigMap and restarting it. Retry latency is then not distorted by the
   exponential backoff. `--skip-backoff` leaves the scheduler untouched.
6. Writes `setup_applied.json` as a record of what was applied.

Setup describes a scenario, not a single run: the cluster configuration is the
same for all replicas, and only the task sequence changes.

```bash
python setup.py --scenario scenarios/conflicts-rho020
# writes results/conflicts-rho020/setup/setup_applied.json
```

Namespaces, deployment names, the ConfigMap and the service ports default to
the layout of this repository and can be overridden through environment
variables such as `NODE_CONTROLLER_NAMESPACE` and `SCHEDULER_CONFIGMAP`.

### `clean.py`

Brings the cluster back to a known state. It runs **before** every replica, so
that a leftover can never contaminate the next run.

1. Deletes all the `TaskRequest` resources in the task namespace, then Jobs
   and Pods as a safety net, and waits until none remain.
2. Clears the wall memory of every worker by removing the `Λ(n)` annotation
   and the sanitizing taint, which is the end state of `Sanitize(n)`.
3. Deletes the stale Events in the task namespace.
4. Verifies the clean state and fails if anything is left.
5. With `--settle N`, waits `N` seconds at the end to realign the
   node-controller timer across runs.

It deliberately does not touch node labels, `NodeProperty` or
`GeographicalGroup`: those are stable across the replicas of a scenario and
belong to `setup.py`.

```bash
python clean.py --scenario scenarios/conflicts-rho020 --settle 30
python clean.py            # default conventions, no scenario needed
```

### `run.py`

Plays one replica of a scenario against a configured and cleaned cluster.
Three roles share one monotonic clock with millisecond precision, independent
of the second-granular timestamps of Kubernetes:

- a **submitter** creates each `TaskRequest` at its planned offset and times
  the admission round trip;
- one **watcher** per resource kind (`TaskRequest`, Job, Pod, Event, Node)
  stamps every event on arrival;
- a **recorder** correlates `TaskRequest`, Job and Pod and fills the per-task
  records.

Outputs under `results/<name>/run_<replica>/`:

| File | Content |
| --- | --- |
| `tasks.csv` | one row per task: submission, admission, translation, scheduling, rejections by cause, execution, outcome |
| `events.csv` | one row per watch event, appended live as a crash-safety net |
| `nodes.csv` | timeline of taint and `Λ(n)` for every node change |
| `summary.json` | counts, latency statistics, breakdown of block causes, makespan |

The most used columns of `tasks.csv`:

| Column | Meaning |
| --- | --- |
| `latency_s` | scheduling latency, from submission to Pod binding |
| `blocked` | whether the Pod was rejected at least once before being bound |
| `block_cause` | `none`, `wall`, `taint` or `mixed`, according to what the Pod ran into while waiting |
| `wait_s` | time from the first rejection to the binding, for blocked tasks |
| `context_degree` | number of contexts in conflict with the task's context |
| `node` | node the task was bound to |

```bash
python run.py --scenario scenarios/conflicts-rho020 --replica 0
python run.py --scenario scenarios/conflicts-rho020 --replica 0 --timeout-seconds 0
```

Every option defaults to the value in the scenario. `--timeout-seconds 0`
disables the global timeout, so the run ends only when every task has reached
a terminal state; this is what the sweeps use. `--mode baseline` submits plain
Jobs to the default scheduler, bypassing `TaskRequest`, Gatekeeper and the
plugins, and is available for overhead comparisons.

`run.py` is a thin entry point. The implementation lives in `runner/`:

| Module | Content |
| --- | --- |
| `core` | the `Runner` that orchestrates submitter, watchers, recorder and outputs |
| `scenario` | conventions and loading of the task plan |
| `record` | the per-task record and its derived columns |
| `watchers` | one watch stream per resource kind |
| `recorder` | correlation of the resources and the node timeline |
| `output` | CSV and JSON writers |
| `utils` | pure helpers |

## Analysis

The two notebooks load the runs through `analysis/utils.py`, aggregate them
per scenario and replica, and produce the figures in `analysis/figures/` and
the tables in `analysis/tables/`. Curves report the mean across replicas with
a band of one standard deviation between replicas.

The statistical tests are run on the per-replica mean latencies:

- **Kruskal-Wallis** for the overall effect of the independent variable;
- **Spearman** correlation for the monotonic trend of latency with `ρ`;
- **Mann-Whitney U**, two-sided, between adjacent values of `τ`, to locate the
  region in which the latency is statistically indistinguishable from the
  minimum.

`analysis/utils.py` also provides `verify_no_wall_violation`, which replays
the node timelines and checks that no task was ever bound to a node whose
memory was in conflict with it. It is a correctness check of the prototype
against the model, independent of the performance figures.

## Notes on timing

- The Pod backoff of the scheduler is pinned by `setup.py`; keep the
  sanitization interval well above it, otherwise retry latency is dominated by
  the backoff and not by the wait for sanitization.
- Admission and translation add a fixed cost of some hundreds of milliseconds
  per task. A submission rate of one task per second keeps consecutive
  submissions from overlapping.
- A run must last long enough to cover several sanitization cycles, also for
  the largest interval in the grid. With few cycles the measured latency
  depends mostly on when they happen to fall, and the variance grows.
- All the components run on a single machine, so absolute latencies are not
  representative of a production cluster. The comparisons between scenarios
  are what matters.
