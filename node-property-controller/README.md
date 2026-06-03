# Node Property Controller

Kubernetes controller that classifies cluster nodes against property definitions (`NodePropertyDefinition` CRD) and writes the resulting levels as node labels.

For each node `n` and each property `p`, the controller computes the highest level whose DNF expression is satisfied by the node's attribute labels, then labels the node with:

```
property.node.policydriven.unimi.it/<p> = <level>
```

## Architecture

The controller watches two kinds of objects:

- `NodePropertyDefinition` CRDs (group `policydriven.unimi.it`)
- `Node` resources

Whenever either changes, the affected nodes are re-evaluated and their property labels updated.

## Configuration

All configurable via environment variables (with defaults):

| Variable           | Default                                | Description                        |
| ------------------ | -------------------------------------- | ---------------------------------- |
| `GROUP`            | `policydriven.unimi.it`                | CRD API group                      |
| `VERSION`          | `v1alpha1`                             | CRD API version                    |
| `PLURAL`           | `node-properties`                      | CRD plural name                    |
| `ATTRIBUTE_PREFIX` | `attribute.node.policydriven.unimi.it` | Prefix for input attribute labels  |
| `PROPERTY_PREFIX`  | `property.node.policydriven.unimi.it`  | Prefix for output property labels  |
| `LOG_LEVEL`        | `INFO`                                 | One of DEBUG, INFO, WARNING, ERROR |

## Running locally

Requires Python 3.12+, a working `kubectl` context and the CRD already applied.

```bash
pip install -r requirements.txt
kopf run main.py
```

## Deploying to Kubernetes

For `kind`:

```bash
# build the image and load it into the cluster 
docker build -t node-property-controller:latest .
kind load docker-image node-property-controller:latest --name <cluster-name>

# namespace, RBAC, network policy, deployment
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/rbac.yaml
kubectl apply -f k8s/network-policy.yaml
kubectl apply -f k8s/deployment.yaml

# verify it's running
kubectl -n node-property-controller get pods
kubectl -n node-property-controller logs -l app.kubernetes.io/name=node-property-controller -f
```

## Testing

```bash
pip install pytest pytest-cov
pytest -v --cov=src
```
