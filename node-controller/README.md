# Node Controller

Kubernetes controller, built with [kopf](https://kopf.readthedocs.io/), that
looks after the nodes on behalf of the scheduling pipeline. It has two
independent jobs:

- **classification**: it derives the property class `α(n)` of every worker
  node from its attribute labels and the `NodeProperty` resources;
- **sanitization**: it periodically runs the procedure `Sanitize(n)` that
  resets the Chinese Wall memory `Λ(n)` of a node.

It never takes part in the scheduling of a single task. It reacts to changes
of nodes and properties and keeps the information the other components rely on
up to date.

## Node classification

A `NodeProperty` describes an abstract property, such as `security` or
`computation`, as an ordered list of levels. Each level is a boolean expression
in disjunctive normal form over the concrete attributes of a node.

```yaml
apiVersion: policydriven.unimi.it/v1alpha1
kind: NodeProperty
metadata:
  name: security
spec:
  weight: 1            # w_p, used by the scheduler in φ_prop
  levels:
    - disjunction:     # level 1: cert = certC
        - clause:
            - { key: cert, operator: Eq, values: ["certC"] }
    - disjunction:     # level 2: (cert = certB) OR (isolation = strict)
        - clause:
            - { key: cert, operator: Eq, values: ["certB"] }
        - clause:
            - { key: isolation, operator: Eq, values: ["strict"] }
```

The number of a level is its position in the list, starting from 1, so the
levels are contiguous by construction. Level 0 is implicit, always satisfied
and must not be declared.

The attributes of a node are the labels with the prefix
`attribute.node.policydriven.unimi.it/`, set by whoever administers the
cluster. In the example above, `cert` refers to the label
`attribute.node.policydriven.unimi.it/cert`.

For every worker node and every property, the controller evaluates all the
levels and writes the highest satisfied one as a label:

```
property.node.policydriven.unimi.it/<property> = <level>
```

Level 0 is represented by the absence of the label. Control-plane nodes are
skipped.

| Operator | Values | Satisfied when |
| --- | --- | --- |
| `Eq`, `NotEq` | exactly one | the attribute is equal, or not equal, to the value |
| `Gt`, `Gte`, `Lt`, `Lte` | exactly one integer | the attribute compares accordingly as an integer |
| `In`, `NotIn` | one or more | the attribute is, or is not, among the values |
| `Exists`, `NotExists` | none | the attribute is present, or absent |

The constraints on the values are enforced by the CRD schema, see
[`k8s/crds/node-property-crd.yaml`](../k8s/crds/node-property-crd.yaml).

### When labels are recomputed

| Event | Effect |
| --- | --- |
| a node joins the cluster | its level is computed for every known property |
| a `NodeProperty` is created | its level is computed on every node |
| a `NodeProperty` is deleted | the corresponding label is removed from every node |
| the controller restarts | everything is recomputed |

Updates to an existing node or `NodeProperty` are **ignored by default**. The
model assumes that metadata does not change once created, which rules out
time-of-check to time-of-use races along the scheduling pipeline. Setting
`DEBUG_MODE=true` registers the update handlers as well; the evaluation
harness relies on it to relabel the nodes between scenarios.

## Node sanitization

Every task scheduled on a node leaves its contexts in the node annotation
`trace.node.policydriven.unimi.it/contexts`, which represents `Λ(n)`. The
controller clears it with the periodic strategy: a timer fires on every worker
node each `SANITIZE_INTERVAL_SECONDS` and runs the following steps.

| Step of `Sanitize(n)` | Implementation |
| --- | --- |
| `sanitizing(n) ← true` | adds the taint `trace.node.policydriven.unimi.it/sanitizing:NoSchedule`, so the node leaves the candidate set |
| `WaitForCompletion(n)` | checks whether Pods bound by the custom scheduler are still active on the node; if so, the taint stays and the rest is retried at the next tick |
| `ClearResidualTraces(n)` | simulated, optionally sleeping for `CLEAR_TRACES_SIMULATION_SECONDS` |
| `Λ(n) ← ∅`, `sanitizing(n) ← false` | removes the annotation and the taint, so the node is a candidate again |

A node whose memory is already empty is left untouched, without even being
tainted: there is nothing to protect, hence nothing to sanitize.

`WaitForCompletion` is deliberately not a blocking wait. Only the Pods whose
`schedulerName` is the custom scheduler count as active, since system and
DaemonSet Pods run permanently on every node and are not what `Λ(n)` protects
against.

Setting `SANITIZE_INTERVAL_SECONDS=0` disables the timer altogether.

### Manual sanitization

The same logic can be run on demand, once for every worker node, through a
one-off Job. This is handy for tests and troubleshooting.

```bash
kubectl apply -f k8s/sanitize.yaml
kubectl -n node-controller logs job/node-sanitize-manual
```

As with the timer, a node that still has active task Pods is only tainted and
its memory is not cleared. Run the Job again once those Pods have completed;
Job names cannot be reused, so delete the previous one first:

```bash
kubectl -n node-controller delete job node-sanitize-manual
```

To inspect the state of the nodes:

```bash
# Memory and taints of every node
kubectl get nodes -o custom-columns='NODE:.metadata.name,LAMBDA:.metadata.annotations.trace\.node\.policydriven\.unimi\.it/contexts,TAINTS:.spec.taints[*].key'

# Property labels
kubectl get nodes -L property.node.policydriven.unimi.it/security,property.node.policydriven.unimi.it/computation
```

## Layout

```
main.py                 kopf handlers and the sanitization timer
sanitize.py             entry point of the manual sanitization Job
src/controller.py       classification logic and label patching
src/models.py           Condition, Clause, Level, Property, Node
src/operators.py        the operators available in a condition
src/sanitization.py     Sanitizer, the implementation of Sanitize(n)
src/config.py           configuration loaded from environment variables
```

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `GROUP` | `policydriven.unimi.it` | API group of the custom resources |
| `VERSION` | `v1alpha1` | version of the custom resources |
| `NODE_PROPERTIES_PLURAL` | `nodeproperties` | plural name of `NodeProperty` |
| `ATTRIBUTE_PREFIX` | `attribute.node.<GROUP>` | prefix of the attribute labels read from the nodes |
| `PROPERTY_PREFIX` | `property.node.<GROUP>` | prefix of the property labels written on the nodes |
| `TRACE_PREFIX` | `trace.node.<GROUP>` | prefix of the memory annotation and of the sanitizing taint |
| `CONTEXTS_ANNOTATION` | `contexts` | name of the annotation holding `Λ(n)` |
| `SANITIZING_TAINT` | `sanitizing` | name of the taint applied during sanitization |
| `SCHEDULER_NAME` | `policy-driven-scheduler` | scheduler whose Pods are waited for |
| `SANITIZE_INTERVAL_SECONDS` | `60` | period of the sanitization timer, `0` to disable it |
| `CLEAR_TRACES_SIMULATION_SECONDS` | `0` | simulated duration of the trace removal |
| `DEBUG_MODE` | `false` | also react to updates of nodes and properties |
| `LOG_LEVEL` | `INFO` | one of `DEBUG`, `INFO`, `WARNING`, `ERROR` |

## Running locally

Requires Python 3.12, a working `kubectl` context and the CRDs applied.

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
docker build -t node-controller:latest .
kind load docker-image node-controller:latest --name <cluster-name>

# RBAC, deployment, network policy
kubectl apply -f k8s/rbac.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/network-policy.yaml

kubectl -n node-controller rollout restart deployment/node-controller
kubectl -n node-controller rollout status deployment/node-controller --timeout=180s
```

## Testing

```bash
pip install pytest pytest-cov
pytest -v --cov=src
```

The tests need no cluster: the Kubernetes API is replaced by test doubles.
