# Policy-Driven Task Scheduling

Prototype of a policy-driven task scheduler for Kubernetes with data protection
constraints. An issuer submits a task that needs some datasets; the system
decides, on its own, which node of the cluster may run it and which one is the
best choice. The issuer never picks the node and has no view of the
infrastructure.

This repository is the implementation that accompanies the master's thesis
*"Scheduling Policy-Driven di Task in Kubernetes con Vincoli di Protezione dei
Dati"* (Università degli Studi di Milano). The formal model is defined in the
thesis; this document only recalls the notation needed to read the code.

## The model in one page

A task `t` is submitted by an issuer `iss(t)` and requires a set of datasets
`req(t)`. Every node, task and dataset carries metadata, and a set of policies
decides whether a node `n` is admissible for `t`.

| Policy     | Checks                                                                 | Enforced by                                         |
| ---------- | ---------------------------------------------------------------------- | --------------------------------------------------- |
| `c_auth`   | every context of every requested dataset is in `auth(iss(t))`          | Gatekeeper (admission)                              |
| `c_prop`   | the node's property class dominates the effective class `β*(t)`        | `nodeAffinity` built by the task-request-controller |
| `c_geo`    | the node's location belongs to the effective group `geo*(t)`           | `nodeAffinity` built by the task-request-controller |
| `c_static` | every static dataset in `req(t)` is already hosted on the node         | `nodeAffinity` built by the task-request-controller |
| `c_wall`   | `auth(iss(t))` has no conflict of interest with the node memory `Λ(n)` | scheduler plugin `WallFilter`                       |

Among the admissible nodes, two indicators in `[0, 1]` are combined into a
weighted score and the node with the highest score wins.

| Indicator    | Prefers                                                               | Computed by                      |
| ------------ | --------------------------------------------------------------------- | -------------------------------- |
| `φ_prop`     | the node whose property class is closest to `β*(t)` (least privilege) | scheduler plugin `PropScore`     |
| `φ_transfer` | the node that already hosts the largest share of `req(t)`             | scheduler plugin `TransferScore` |

`c_wall` is the only dynamic policy. Each scheduled task deposits its
contextual footprint `ctx*(t)` on the chosen node, so `Λ(n)` grows over time;
a periodic sanitization procedure takes the node out of the pool, waits for its
tasks to finish, clears the residual traces and resets `Λ(n)`.

## Architecture

```
  TaskRequest (namespace "compute")
        │
        ▼
  OPA Gatekeeper ───────────────────────────► dataset-service, context-service
  structural checks, c_auth
        │
        ▼
  task-request-controller ──────────────────► dataset-service
  β*(t), geo*(t), ctx*(t), nodeAffinity
        │  Job
        ▼
  scheduler ────────────────────────────────► dataset-service, context-service
  NodeAffinity (c_prop, c_geo, c_static)
  WallFilter (c_wall), PropScore, TransferScore
        │
        ▼
  worker node ◄────────────────────────────── node-controller
                                    property labels, sanitization
```

| Component                                             | Language        | Role                                                                                |
| ----------------------------------------------------- | --------------- | ----------------------------------------------------------------------------------- |
| [`k8s/`](k8s)                                         | YAML            | CRDs, namespaces, Gatekeeper templates and constraints                              |
| [`dataset-service/`](dataset-service)                 | Python, FastAPI | registry of dataset metadata: `β(d)`, `geo(d)`, `ctx(d)`, `λ(d)`, size, static flag |
| [`context-service/`](context-service)                 | Python, FastAPI | issuer authorizations `auth(i)` and the conflict relation `X_conf`                  |
| [`node-controller/`](node-controller)                 | Python, kopf    | derives the property class `α(n)` of each node and runs the sanitization procedure  |
| [`task-request-controller/`](task-request-controller) | Python, kopf    | translates an admitted `TaskRequest` into a schedulable `Job`                       |
| [`scheduler/`](scheduler)                             | Go              | custom scheduler built on the Kubernetes Scheduling Framework                       |
| [`evaluation/`](evaluation)                           | Python, Jupyter | experimental harness and analysis used in the thesis                                |
| [`examples/`](examples)                               | YAML, JSON      | sample cluster, properties, groups, seed data and task requests                     |
| [`scripts/`](scripts)                                 | Bash            | cluster bootstrap, seeding and end-to-end tests                                     |
| [`docs/`](docs)                                       | LaTeX, PDF      | documentation                                                                       |

Each component has its own README with configuration, deployment and testing details.

### Custom resources

All custom resources belong to the API group `policydriven.unimi.it/v1alpha1`.

| Kind                | Scope      | Short name | Meaning                                                                                       |
| ------------------- | ---------- | ---------- | --------------------------------------------------------------------------------------------- |
| `TaskRequest`       | namespaced | `treq`     | a task: `issuer`, `datasets`, optional `requirements` and `geo`                               |
| `NodeProperty`      | cluster    | `nprop`    | an abstract property with ordered levels, each defined by a DNF expression on node attributes |
| `GeographicalGroup` | cluster    | `geo`      | a set of locations, possibly including other groups                                           |

### Naming conventions

The components communicate through labels and annotations. The defaults below
are shared by all of them and can be overridden through environment variables.

| Key                                                                                | On                         | Written by              | Meaning                                           |
| ---------------------------------------------------------------------------------- | -------------------------- | ----------------------- | ------------------------------------------------- |
| `attribute.node.policydriven.unimi.it/<a>`                                         | Node (label)               | cluster admin           | concrete attribute `n[a]`                         |
| `property.node.policydriven.unimi.it/<p>`                                          | Node (label)               | node-controller         | level `α_p(n)`; absent means level 0              |
| `topology.node.policydriven.unimi.it/location`                                     | Node (label)               | cluster admin           | `loc(n)`                                          |
| `trace.node.policydriven.unimi.it/contexts`                                        | Node (annotation)          | scheduler               | node memory `Λ(n)`, a JSON list                   |
| `trace.node.policydriven.unimi.it/sanitizing`                                      | Node (taint, `NoSchedule`) | node-controller         | the node is being sanitized                       |
| `scheduling.task.policydriven.unimi.it/{issuer,datasets,betaStar,geoStar,ctxStar}` | Pod (annotations)          | task-request-controller | `iss(t)`, `req(t)`, `β*(t)`, `geo*(t)`, `ctx*(t)` |

## Quick start

Requirements: Docker, [kind](https://kind.sigs.k8s.io/), `kubectl`, `helm`
(only for the monitoring stack) and `openssl`. The policy tests also need
[`gator`](https://open-policy-agent.github.io/gatekeeper/website/docs/gator/).

```bash
# 1. Create the kind cluster and deploy every component
make init

# 2. Load the example properties, groups, contexts and datasets
make populate-examples

# 3. Submit a task and follow it
kubectl apply -f examples/task-request/t1.yaml
kubectl get treq -n compute
kubectl get pods -n compute -o wide
```

`make init` creates a cluster with one control plane and five workers from
[`examples/cluster-config.yaml`](examples/cluster-config.yaml), which
reproduces the running example of the thesis: node attributes, locations and
the expected outcome of each task are documented in the comments of the files
under [`examples/task-request/`](examples/task-request).

### Make targets

| Target                        | Description                                                                                |
| ----------------------------- | ------------------------------------------------------------------------------------------ |
| `init`                        | create the cluster from `CLUSTER_CONFIG_FILE` and deploy all components                    |
| `init-nodes-count`            | same, but generate the cluster from `CONTROL_PLANE_COUNT`, `WORKER_COUNT` and `NODE_IMAGE` |
| `populate-examples`           | apply the example resources and seed the two services                                      |
| `test-policies`               | run the Gatekeeper policy tests                                                            |
| `test-examples`               | run the end-to-end tests on the example task requests                                      |
| `start` / `stop`              | start or stop the cluster containers without deleting them                                 |
| `delete`                      | delete the cluster                                                                         |
| `headlamp` / `headlamp-token` | port-forward the Headlamp dashboard, or just print a login token                           |
| `grafana`                     | print the Grafana credentials and port-forward the dashboard                               |

### Bootstrap options

| Variable                               | Default (Makefile)             | Description                                         |
| -------------------------------------- | ------------------------------ | --------------------------------------------------- |
| `CLUSTER_NAME`                         | `kind`                         | name of the kind cluster                            |
| `CLUSTER_CONFIG_FILE`                  | `examples/cluster-config.yaml` | kind configuration used by `make init`              |
| `CONTROL_PLANE_COUNT` / `WORKER_COUNT` | `1` / `5`                      | used by `make init-nodes-count`                     |
| `NODE_IMAGE`                           | `kindest/node:v1.34.8`         | node image, Kubernetes 1.34                         |
| `ENABLE_DASHBOARD`                     | `true`                         | install Headlamp                                    |
| `ENABLE_MONITORING`                    | `true`                         | install kube-prometheus-stack and Loki              |
| `DATASET_SERVICE_LIGHT_MODE`           | `true`                         | run dataset-service on SQLite instead of PostgreSQL |
| `CONTEXT_SERVICE_LIGHT_MODE`           | `true`                         | run context-service on SQLite instead of PostgreSQL |

When both services run in light mode the CloudNativePG operator is not
installed at all, which makes the bootstrap considerably faster.

## Bootstrap scripts

[`scripts/init-cluster.sh`](scripts/init-cluster.sh) runs the steps in
[`scripts/steps/`](scripts/steps) in a fixed order. Every step can also be run
on its own; its header documents the prerequisites and the variables it reads.

| Order | Step                         | What it does                                                                   |
| ----- | ---------------------------- | ------------------------------------------------------------------------------ |
| 1     | `cluster.sh`                 | creates the kind cluster, or reuses an existing one                            |
| 2     | `headlamp.sh`                | optional dashboard                                                             |
| 3     | `monitoring-stack.sh`        | optional Prometheus, Grafana and Loki                                          |
| 4     | `namespaces-crds.sh`         | applies `k8s/namespaces` and `k8s/crds`                                        |
| 5     | `gatekeeper.sh`              | installs Gatekeeper with External Data enabled, then templates and constraints |
| 6     | `cloudnative-pg.sh`          | PostgreSQL operator, skipped in light mode                                     |
| 7     | `node-controller.sh`         | builds, loads and deploys the node-controller                                  |
| 8     | `dataset-service.sh`         | TLS material, image, manifests                                                 |
| 9     | `context-service.sh`         | TLS material, image, manifests                                                 |
| 10    | `task-request-controller.sh` | image and manifests, plus the dataset-service CA                               |
| 11    | `scheduler.sh`               | image, scheduler configuration and the CAs of both services                    |

Other scripts:

- `gen-certs.sh` generates a self-signed CA and a server certificate for one of
  the two services. `SVC` and `NS` must always be passed explicitly.
- `populate-examples.sh` applies `examples/node-property` and
  `examples/geographical-group`, then seeds the two services through a one-off
  `Job` each.
- `test-policies.sh [gator|manual|all]` verifies the policies, see below.
- `test-examples.sh` submits every example task request and checks the outcome.

## Admission policies

The Gatekeeper policies live in [`k8s/policies/`](k8s/policies), one directory
per policy with a `template.yaml`, a `constraint.yaml` and a `tests/` folder.

| Policy                                     | Rejects a `TaskRequest` when                                                                                      |
| ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------- |
| `validate-task-request-namespace`          | it is not created in the `compute` namespace                                                                      |
| `validate-task-request-properties`         | `requirements` names a `NodeProperty` or a level that does not exist                                              |
| `validate-task-request-geographical-group` | `geo` names a `GeographicalGroup` that does not exist                                                             |
| `validate-task-request-datasets`           | a dataset or the issuer does not exist, a dataset references a missing property or group, or `c_auth` is violated |

The first three are self-contained and are tested offline with `gator verify`.
The last one queries dataset-service and context-service through the External
Data protocol, so it can only be tested against a live, populated cluster.

```bash
make test-policies                       # both kinds
bash scripts/test-policies.sh gator      # offline suites only
bash scripts/test-policies.sh manual     # live cluster only
```

## Testing

| Level                         | Command                                    | Needs a cluster                   |
| ----------------------------- | ------------------------------------------ | --------------------------------- |
| Unit tests, Python components | `pytest -v` inside the component directory | no                                |
| Unit tests, scheduler         | `go test ./...` inside `scheduler/`        | no                                |
| Policy tests                  | `make test-policies`                       | only for the external-data policy |
| End-to-end tests              | `make test-examples`                       | yes, initialized and populated    |

The same sequence runs in CI on every push and pull request to `main`, see
[`.github/workflows/ci.yaml`](.github/workflows/ci.yaml).

## Scope of the prototype

The prototype makes a few deliberate simplifications, discussed in the thesis:

- **Black-box tasks.** A `TaskRequest` carries no image. The generated `Job`
  runs a placeholder container that sleeps for a configurable number of
  seconds.
- **Logical data management.** Dataset placement is metadata only. The cost of
  moving data is evaluated through `φ_transfer`, but no transfer is performed.
- **Simulated trace removal.** The sanitization procedure is fully implemented
  except for the actual wiping of the node, which depends on hardware and
  operating system.
- **Immutable metadata.** Once created, the metadata of nodes, datasets and
  issuers is assumed not to change while a task goes through the pipeline.
- **Single cluster, single scheduler.** Pods are scheduled one at a time by one
  scheduler instance.
- **No authentication on the services.** Access is restricted by
  `NetworkPolicy`; note that kind's default CNI does not enforce it.
