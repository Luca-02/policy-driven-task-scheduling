# Scheduler

Custom Kubernetes scheduler that completes the policy evaluation and performs
the optimal node selection. It is a standard `kube-scheduler` binary compiled
together with three out-of-tree plugins, written against the
[Scheduling Framework](https://kubernetes.io/docs/concepts/scheduling-eviction/scheduling-framework/)
of Kubernetes 1.34.

Only the Pods that ask for it are handled by this scheduler: the
task-request-controller sets `schedulerName: policy-driven-scheduler` on every
`Job` it creates, while everything else in the cluster keeps using the default
scheduler.

## What it does

By the time a Pod reaches the scheduler, the policies `c_prop`, `c_geo` and
`c_static` have already been encoded as `nodeAffinity` by the
task-request-controller, so they are evaluated by the built-in `NodeAffinity`
plugin. The plugins in this module cover what cannot be expressed as a static
constraint on node labels.

| Plugin | Extension points | Implements |
| --- | --- | --- |
| `WallFilter` | Filter, Reserve, PostBind | the Chinese Wall policy `c_wall` and the update of the node memory `Λ(n)` |
| `PropScore` | Score | the property excess indicator `φ_prop` |
| `TransferScore` | PreScore, Score | the transfer cost indicator `φ_transfer` |

The plugins are wired together in
[`k8s/scheduler-config.yaml`](k8s/scheduler-config.yaml), which also sets the
weights of the score function. By default `TransferScore` weighs 2 and
`PropScore` weighs 1, so data locality takes priority over property excess.

### WallFilter

**Filter** runs for every candidate node. It reads the issuer from the Pod
annotations and `Λ(n)` from the node annotation, then asks context-service
whether

```
(auth(iss(t)) × Λ(n)) ∩ X_conf = ∅
```

A node with an empty memory is accepted without calling the service. If the
service cannot be reached the plugin returns an error rather than letting the
Pod through.

**PostBind** runs once, after the Pod has been bound, and writes
`Λ(n) ← Λ(n) ∪ ctx*(t)` on the selected node. Doing this in Filter would be
wrong, because Filter is evaluated speculatively on every candidate.

**Reserve** closes the gap between the two. The binding cycle is asynchronous
with respect to the scheduling cycle, and the annotation written in PostBind
still needs to propagate through the informer cache. Without any precaution,
several Pods released together onto a freshly sanitized node could all be
filtered against the same empty `Λ(n)` and end up depositing conflicting
contexts on it. Reserve is synchronous and always precedes the Filter of the
next Pod, so `ctx*(t)` is recorded there in an in-memory store
([`pkg/wallfilter/assumed.go`](pkg/wallfilter/assumed.go)), and Filter
evaluates `c_wall` against the node annotation merged with the assumed
contexts. An assumption is dropped when:

- `Unreserve` is called because the bind failed;
- the node annotation catches up and already reports the context;
- its TTL expires (`WALL_ASSUMED_TTL_SECONDS`, 5 seconds by default), a
  backstop for the case in which the PostBind write itself failed.

### PropScore

Reads `β*(t)` from the Pod annotation and `α(n)` from the node's property
labels, then computes

```
Δ(n,t)      = Σ_p  w_p · (α_p(n) − β*_p(t)) / (max L_p − β*_p(t))
Δ_max(t)    = Σ_p  w_p
φ_prop(n,t) = 1 − Δ(n,t) / Δ_max(t)
```

where the sums range over the properties with `β*_p(t) < max L_p`. If no
property contributes, the node is trivially ideal and `φ_prop = 1`. The maximum
level and the weight of each property come from the `NodeProperty` resources,
kept in sync by an informer
([`internal/nodeproperties`](internal/nodeproperties)), so no per-cycle
preparation is needed.

### TransferScore

**PreScore** issues a single request to dataset-service for all the datasets
in `req(t)` and stores size and placement in the cycle state. **Score** then
computes, for each admissible node and without any further I/O,

```
φ_transfer(n,t) = 1 − size(remote(n,t)) / size(req(t))
```

where `remote(n,t)` is the set of requested datasets not hosted on `n`.

Both indicators are mapped from `[0, 1]` to the framework range
`[0, MaxNodeScore]`. No normalization against the observed maximum is applied,
so the scores keep their absolute meaning. The framework sums the weighted
contributions and picks the node with the highest total; ties are broken at
random among the best nodes.

## Layout

```
cmd/main.go                 entry point, wraps the upstream scheduler command
internal/registry           the list of plugins compiled into the binary
internal/config             configuration loaded from environment variables
internal/contexts           HTTP client for context-service (wall check)
internal/datasets           HTTP client for dataset-service (batch query)
internal/nodeproperties     informer-backed cache of NodeProperty resources
internal/nodes              read and update of the Λ(n) node annotation
pkg/wallfilter              WallFilter plugin and the assumed-contexts store
pkg/propscore               PropScore plugin
pkg/transferscore           TransferScore plugin
k8s/                        Deployment, RBAC, NetworkPolicy, scheduler config
```

To add or remove a plugin, edit `internal/registry/registry.go` and the
profile in `k8s/scheduler-config.yaml`; `cmd/main.go` does not change.

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `GROUP` | `policydriven.unimi.it` | API group of the custom resources |
| `CRD_VERSION` | `v1alpha1` | version of the custom resources |
| `NODE_PROPERTY_RESOURCE_PLURAL` | `nodeproperties` | plural name of the `NodeProperty` resource |
| `DATASET_SERVICE_URL` | `https://127.0.0.1:8443` | base URL of dataset-service |
| `DATASET_SERVICE_CA_FILE` | (unset) | CA certificate used to verify dataset-service |
| `CONTEXT_SERVICE_URL` | `https://127.0.0.1:8443` | base URL of context-service |
| `CONTEXT_SERVICE_CA_FILE` | (unset) | CA certificate used to verify context-service |
| `TASK_POD_ANNOTATION_PREFIX` | `scheduling.task.<GROUP>` | prefix of the task annotations on the Pod |
| `NODE_PROPERTY_LABEL_PREFIX` | `property.node.<GROUP>` | prefix of the property labels on the node |
| `NODE_TRACE_ANNOTATION_PREFIX` | `trace.node.<GROUP>` | prefix of the trace annotations on the node |
| `DATASETS_ANNOTATION_KEY` | `datasets` | annotation carrying `req(t)` |
| `BETA_STAR_ANNOTATION_KEY` | `betaStar` | annotation carrying `β*(t)` |
| `ISSUER_ANNOTATION_KEY` | `issuer` | annotation carrying `iss(t)` |
| `CTX_STAR_ANNOTATION_KEY` | `ctxStar` | annotation carrying `ctx*(t)` |
| `CONTEXTS_ANNOTATION_KEY` | `contexts` | node annotation carrying `Λ(n)` |
| `WALL_ASSUMED_TTL_SECONDS` | `5` | lifetime of an assumed deposit not yet visible on the node |

The annotation and label names must match those used by the
task-request-controller and the node-controller.

## Building and testing

Requires Go 1.24.

```bash
go build ./...
go test ./...
```

The tests need no cluster: the service clients run against `httptest` servers
and the plugin logic is exercised through plain functions.

## Deploying to Kubernetes

On kind, `scripts/init-cluster.sh` takes care of everything. To redeploy the
scheduler by hand, from the repository root:

```bash
# Build the image and load it into the cluster
docker build -t scheduler:latest scheduler
kind load docker-image scheduler:latest --name <cluster-name>

# Scheduler profile
kubectl create configmap scheduler-config \
    --from-file=scheduler-config.yaml=scheduler/k8s/scheduler-config.yaml \
    -n scheduler --dry-run=client -o yaml | kubectl apply -f -

# RBAC, deployment, network policy
kubectl apply -f scheduler/k8s/rbac.yaml
kubectl apply -f scheduler/k8s/deployment.yaml
kubectl apply -f scheduler/k8s/network-policy.yaml

kubectl -n scheduler rollout restart deployment/scheduler
kubectl -n scheduler rollout status deployment/scheduler --timeout=180s
```

The Deployment mounts the CA certificates of the two services from the secrets
`dataset-service-tls` and `context-service-tls`, which must exist in the
`scheduler` namespace. The bootstrap script copies them from the namespaces of
the two services; they have to be copied again whenever the certificates are
regenerated.

The scheduler logs every decision at verbosity 2 and the intermediate values
at verbosity 4:

```bash
kubectl -n scheduler logs deployment/scheduler -f
```
