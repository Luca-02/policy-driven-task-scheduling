# TaskRequest Controller

Kubernetes controller, built with [kopf](https://kopf.readthedocs.io/), that
turns an admitted `TaskRequest` into a `Job` the custom scheduler can place.

This step belongs to neither of the two logical phases of the model: it does
not evaluate policies and it does not rank nodes. It prepares the data the
following steps need and encodes three of the policies as native Kubernetes
constraints, leaving their evaluation to the scheduler.

## What it does

When a `TaskRequest` appears in the task namespace (`compute` by default), the
controller runs the following pipeline.

1. Sets `status.phase` to `Pending`.
2. Fetches the metadata of all the datasets in `req(t)` from dataset-service
   with a single call to `POST /datasets/query`.
3. Computes the effective property class
   `β*(t) = β(t) ⊔ ⨆ β(d)`, the component-wise maximum between the task
   requirements and those of every requested dataset.
4. Computes the effective geographical group
   `geo*(t) = geo(t) ∩ ⋂ geo(d)`, resolving nested `GeographicalGroup`
   resources recursively. An entity without a group imposes no constraint.
5. Computes the contextual footprint `ctx*(t) = ⋃ ctx(d)`.
6. Computes the intersection of `λ(d)` over the static datasets in `req(t)`,
   that is, the nodes that already host all of them.
7. Creates a `Job` with the same name as the `TaskRequest`, owned by it, and
   sets `status.phase` to `Scheduled`.

The request fails early, with `status.phase = Failed` and an explanatory
`status.message`, when no node could ever satisfy it:

- a requested dataset does not exist;
- `geo*(t)` is empty, because the geographical constraints are incompatible;
- the static datasets have no node in common.

A temporary failure of dataset-service is retried after 10 seconds instead.

### The generated Job

The Pod template of the `Job` carries the computed values as annotations, so
that the scheduler plugins can read them from the Pod without recomputing
anything.

| Annotation (prefix `scheduling.task.policydriven.unimi.it/`) | Content |
| --- | --- |
| `issuer` | `iss(t)` |
| `datasets` | `req(t)`, JSON list |
| `betaStar` | `β*(t)`, JSON object |
| `geoStar` | `geo*(t)`, JSON list of locations |
| `ctxStar` | `ctx*(t)`, JSON list |

Three policies are translated into a single required `nodeAffinity` term.

| Policy | Match expression |
| --- | --- |
| `c_prop` | for each property `p` with `β*_p(t) > 0`: label `property.node.policydriven.unimi.it/<p>` `Gt` `β*_p(t) − 1`, which is `α_p(n) ≥ β*_p(t)` on integer levels |
| `c_geo` | label `topology.node.policydriven.unimi.it/location` `In` `geo*(t)`; omitted when there is no geographical constraint |
| `c_static` | label `kubernetes.io/hostname` `In` the intersection computed at step 6; omitted when no static dataset is requested |

`c_wall` is not encoded here: it depends on the node memory `Λ(n)`, a dynamic
state that cannot be expressed as a constraint on labels, and is evaluated by
the scheduler plugin `WallFilter`.

The Job also sets `schedulerName` to the custom scheduler, `backoffLimit: 0`
and `restartPolicy: Never`. Since tasks are treated as black boxes, the
container is a placeholder (`busybox:musl`) that logs a line per second for
`TASK_SIMULATED_DURATION_SECONDS` seconds.

### Status tracking

The controller also watches the Jobs in the task namespace and reflects their
outcome on the originating `TaskRequest`, found through the label
`scheduling.task.policydriven.unimi.it/taskRequestRef`.

| Phase | Meaning |
| --- | --- |
| `Pending` | accepted, the Job has not been created yet |
| `Scheduled` | the Job exists and has been handed over to the scheduler |
| `Complete` | the Job finished successfully |
| `Failed` | terminal failure, see `status.message` |

Note that `Scheduled` means the Job was created, not that a node has been
found. A task blocked by `c_wall` stays `Scheduled` with its Pod `Pending`
until a node becomes admissible.

```bash
kubectl get treq -n compute
kubectl describe treq <name> -n compute
```

Reconciliation is idempotent. On restart the controller resumes every
`TaskRequest`: terminal ones are skipped, `Scheduled` ones are synced from
their Job, the others go through the full pipeline.

### Geographical groups

The controller keeps an in-memory registry of the `GeographicalGroup`
resources, updated on create, update and delete events. A group is resolved to
its set of locations by following `includes` recursively; cycles and missing
references are skipped.

## Layout

```
main.py                 kopf handlers for TaskRequest, Job and GeographicalGroup
src/controller.py       reconciliation pipeline and status management
src/annotation.py       computation of β*(t), geo*(t), ctx*(t) and the static nodes
src/geo.py              recursive resolution of geographical groups
src/job_builder.py      construction of the Job, its annotations and nodeAffinity
src/dataset_client.py   HTTP client for dataset-service
src/config.py           configuration loaded from environment variables
```

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `GROUP` | `policydriven.unimi.it` | API group of the custom resources |
| `VERSION` | `v1alpha1` | version of the custom resources |
| `TASK_REQUESTS_PLURAL` | `taskrequests` | plural name of `TaskRequest` |
| `GEOGRAPHICAL_GROUPS_PLURAL` | `geographicalgroups` | plural name of `GeographicalGroup` |
| `TASK_REQUEST_KIND` | `TaskRequest` | kind used in the owner reference |
| `TASK_NAMESPACE` | `compute` | the only namespace in which tasks are handled |
| `JOB_LABEL_PREFIX` | `scheduling.task.<GROUP>` | prefix of the labels set on the Job |
| `JOB_ANNOTATION_PREFIX` | `scheduling.task.<GROUP>` | prefix of the annotations set on the Job |
| `TASK_REQUEST_REF_LABEL` | `taskRequestRef` | label linking a Job to its `TaskRequest` |
| `ISSUER_ANNOTATION` | `issuer` | annotation carrying `iss(t)` |
| `DATASETS_ANNOTATION` | `datasets` | annotation carrying `req(t)` |
| `BETA_STAR_ANNOTATION` | `betaStar` | annotation carrying `β*(t)` |
| `GEO_STAR_ANNOTATION` | `geoStar` | annotation carrying `geo*(t)` |
| `CTX_STAR_ANNOTATION` | `ctxStar` | annotation carrying `ctx*(t)` |
| `NODE_PROPERTY_PREFIX` | `property.node.<GROUP>` | prefix of the property labels on the nodes |
| `NODE_TOPOLOGY_LOCATION_LABEL` | `topology.node.<GROUP>/location` | node label holding `loc(n)` |
| `SCHEDULER_NAME` | `policy-driven-scheduler` | scheduler assigned to the generated Jobs |
| `TASK_SIMULATED_DURATION_SECONDS` | `5` | duration of the placeholder task |
| `TASK_TTL_SECONDS_AFTER_FINISHED` | (unset) | if set, finished Jobs are garbage-collected after this many seconds |
| `DATASET_SERVICE_URL` | `https://127.0.0.1:8443` | base URL of dataset-service |
| `DATASET_SERVICE_CA_FILE` | (unset) | CA certificate used to verify dataset-service |
| `LOG_LEVEL` | `INFO` | one of `DEBUG`, `INFO`, `WARNING`, `ERROR` |

The annotation and label names must match those expected by the scheduler and
written by the node-controller.

## Running locally

Requires Python 3.12, a working `kubectl` context, the CRDs applied and a
reachable dataset-service.

```bash
pip install -r requirements.txt
kopf run main.py --all-namespaces
```

Variables can be placed in a `.env` file, loaded at startup.

## Deploying to Kubernetes

On kind, `scripts/init-cluster.sh` takes care of everything. To redeploy the
controller by hand, from this directory:

```bash
# Build the image and load it into the cluster
docker build -t task-request-controller:latest .
kind load docker-image task-request-controller:latest --name <cluster-name>

# RBAC, deployment, network policy
kubectl apply -f k8s/rbac.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/network-policy.yaml

kubectl -n task-request-controller rollout restart deployment/task-request-controller
kubectl -n task-request-controller rollout status deployment/task-request-controller --timeout=180s
```

The Deployment mounts the CA certificate of dataset-service from the secret
`dataset-service-tls`, which must exist in the `task-request-controller`
namespace. The bootstrap script copies it from the `dataset-service`
namespace.

## Testing

```bash
pip install pytest pytest-cov
pytest -v --cov=src
```

The tests need no cluster and no running service: the Kubernetes API and the
dataset client are replaced by test doubles.
