# Node Property Controller

Kubernetes controller that classifies cluster nodes against `NodeProperty` custom resources and writes the resulting levels as node labels.

For each node `n` and each property `p`, the controller computes the highest level whose DNF expression is satisfied by the node's attribute labels, then labels the node with:

```text
property.node.policydriven.unimi.it/<p> = <level>
```

If no positive level is satisfied, level `0` is implicit and the property label is removed.

## Architecture

The controller is implemented in Go with native Kubernetes libraries:

- `client-go` shared informers watch `Node` and `NodeProperty` resources and maintain local caches;
- a rate-limited workqueue reconciles node and property events;
- the dynamic client watches the CRD without generated clients;
- the core client patches node labels only when the desired value differs from the current cached value;
- leader election uses a `coordination.k8s.io/Lease`, so multiple replicas can run for HA while only the leader patches nodes.

See [GO_CONTROLLER_DESIGN.md](GO_CONTROLLER_DESIGN.md) for implementation details and differences from the previous Python/Kopf version. See [FILE_GUIDE.md](FILE_GUIDE.md) for a detailed file-by-file walkthrough.

## Configuration

CRD API identity is not configured through environment variables. It is defined once in `internal/api/v1alpha1` as the standard Kubernetes API group/version/resource: `policydriven.unimi.it/v1alpha1`, resource `nodeproperties`.

Runtime options are configurable through environment variables:

| Variable | Default | Description |
| --- | --- | --- |
| `ATTRIBUTE_PREFIX` | `attribute.node` | Base prefix for input node attribute labels. The controller appends `.policydriven.unimi.it`, so the default full prefix is `attribute.node.policydriven.unimi.it`. |
| `PROPERTY_PREFIX` | `property.node` | Base prefix for computed property labels. The controller appends `.policydriven.unimi.it`, so the default full prefix is `property.node.policydriven.unimi.it`. |
| `LOG_LEVEL` | `INFO` | Reserved for logging configuration. |
| `HEALTH_ADDR` | `:9090` | HTTP health endpoint bind address. |
| `LEADER_ELECTION` | `true` | Enable Kubernetes Lease-based leader election. |
| `LEADER_ELECTION_ID` | `node-property-controller` | Lease name used for leader election. |
| `LEADER_ELECTION_NAMESPACE` | `node-property-controller` | Namespace where the Lease is stored. |
| `RESYNC_PERIOD` | `10h` | Informer resync period. |
| `CONCURRENT_WORKERS` | `2` | Number of reconciliation workers. |

## Running locally

Unit tests that do not need a Kubernetes cluster:

```bash
cd node-property-controller
go test ./internal/domain ./internal/config
```

Run the controller locally against your current kubeconfig with leader election disabled:

```bash
cd node-property-controller
go run main.go --local
```

Run locally with an explicit kubeconfig:

```bash
cd node-property-controller
go run main.go --local --kubeconfig ~/.kube/config
```

## Deploying to Kubernetes

### Build and load the image

For `kind`:

```bash
cd node-property-controller
docker build -t node-property-controller:latest .
kind load docker-image node-property-controller:latest --name <cluster-name>
```

### Apply manifests

```bash
kubectl apply -f k8s/crd/node-property-crd.yaml
kubectl apply -f node-property-controller/k8s/namespace.yaml
kubectl apply -f node-property-controller/k8s/rbac.yaml
kubectl apply -f node-property-controller/k8s/network-policy.yaml
kubectl apply -f node-property-controller/k8s/deployment.yaml
```

The deployment runs three replicas. Only the current leader patches node labels; standby replicas take over if the leader exits.

### Verify

```bash
kubectl -n node-property-controller get pods
kubectl -n node-property-controller get lease node-property-controller -o wide
kubectl -n node-property-controller logs -l app.kubernetes.io/name=node-property-controller -f
kubectl get nodes --show-labels
```

## Testing

```bash
cd node-property-controller
go test ./...
```

If you only want to validate logic without downloading Kubernetes dependencies or reaching a cluster, run:

```bash
cd node-property-controller
go test ./internal/domain ./internal/config
```
