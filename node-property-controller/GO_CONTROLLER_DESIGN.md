# Go Node Property Controller design notes

This controller replaces the previous Python/Kopf implementation with a native Go implementation based on Kubernetes `client-go`.

## What stayed the same

The functional model is unchanged:

- A `NodeProperty` custom resource defines ordered property levels.
- Every level contains a DNF expression: a disjunction of clauses, where every clause is a conjunction of atomic conditions.
- Supported operators remain extensible and keep the same names: `Exists`, `NotExists`, `Eq`, `NotEq`, `In`, `NotIn`, `Gt`, `Lt`, `Gte`, `Lte`.
- Node input attributes are read from labels under `ATTRIBUTE_PREFIX + "." + GroupName`; by default this is `attribute.node.policydriven.unimi.it`.
- Computed property levels are written under `PROPERTY_PREFIX + "." + GroupName`; by default this is `property.node.policydriven.unimi.it`.
- Level `0` remains implicit: if no positive level is satisfied, the output label is removed.
- Control-plane nodes are skipped by default.

## Kubernetes-native improvements in Go

### Shared informers instead of repeated lists

The controller uses `client-go` shared informers for both `Node` objects and the `NodeProperty` custom resources. Informers perform an initial list, then keep an in-memory cache updated through watches. Reconciliation reads from that cache instead of repeatedly calling the Kubernetes API with list operations.

Benefits:

- lower API-server load;
- local, always-current snapshots of nodes and property definitions;
- correct event coalescing through a workqueue;
- natural recovery after watch reconnects through client-go relisting and resync behavior.

### Workqueue-based reconciliation

Events are converted into small queue keys (`node/<name>`, `property/<name>`, `property-deleted/<name>`). Workers consume those keys and retry with rate limiting when patching fails.

This is preferable to doing all work directly inside watch callbacks because callbacks stay fast and the queue provides back-pressure, retry semantics and deduplication.

### Leader election for HA

The deployment runs multiple replicas. All replicas are healthy, but only the elected leader starts the active reconcilers that patch node labels. Leader election uses a native Kubernetes `coordination.k8s.io/Lease` via `client-go`.

If the leader dies, another replica acquires the Lease and starts informers with a fresh cache before reconciling. This avoids split-brain node label updates.

### Minimal patching

Before patching a node, the controller compares the desired label value with the cached current value. It only patches when a label must change or be removed. This reduces no-op API writes and avoids self-induced update loops.

### Dynamic client for the CRD

The CRD identity is defined in `internal/api/v1alpha1` with Kubernetes-style API constants (`GroupName`, `Version`, `Resource`, `GroupVersionResource`) and structs that mirror the CRD schema. The watch path still uses the dynamic client because no generated clientset is committed in this repository; if the API stabilizes further, the next step is generating typed clients/informers with `code-generator` or `controller-tools`.

## State model

The source of truth remains Kubernetes:

- nodes and `NodeProperty` objects are cached by informers;
- parsed property definitions are held in an in-memory map rebuilt from the informer cache at startup;
- computed node labels are persisted back to the Kubernetes API server.

The controller does not need an external database. If the process restarts, a new leader rebuilds state from Kubernetes caches and reconciles all nodes.

## Extending operators

Operators are intentionally simple: `internal/domain/operators.go` defines string constants and a switch-based `EvaluateOperator` function. To add a new operator:

1. add a new operator constant and include it in `KnownOperators`;
2. add a case to `EvaluateOperator`;
3. update the CRD validation enum and any value-shape validation rules;
4. add unit tests for true/false and invalid-input cases.

## Local execution

Local mode uses your current kubeconfig and disables leader election, so it is convenient during development:

```bash
cd node-property-controller
go run main.go --local
```

You still need a reachable Kubernetes API server if you want to exercise real watches and node patches. Unit tests for the domain logic can run without a cluster:

```bash
cd node-property-controller
go test ./internal/domain ./internal/config
```

When module dependencies are available, run the complete suite:

```bash
cd node-property-controller
go test ./...
```

## Cluster deployment

Build the image and load it into kind:

```bash
cd node-property-controller
docker build -t node-property-controller:latest .
kind load docker-image node-property-controller:latest --name <cluster-name>
```

Apply the CRD and controller manifests:

```bash
kubectl apply -f ../k8s/crd/node-property-crd.yaml
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/rbac.yaml
kubectl apply -f k8s/network-policy.yaml
kubectl apply -f k8s/deployment.yaml
```

Verify HA and leader election:

```bash
kubectl -n node-property-controller get pods
kubectl -n node-property-controller get lease node-property-controller -o wide
kubectl -n node-property-controller logs -l app.kubernetes.io/name=node-property-controller -f
```
