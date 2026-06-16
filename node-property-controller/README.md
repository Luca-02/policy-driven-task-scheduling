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

| Variable                 | Default                                | Description                        |
| ------------------------ | -------------------------------------- | ---------------------------------- |
| `GROUP`                  | `policydriven.unimi.it`                | CRD API group                      |
| `VERSION`                | `v1alpha1`                             | CRD API version                    |
| `NODE_PROPERTIES_PLURAL` | `node-properties`                      | CRD NodeProperties plural name     |
| `ATTRIBUTE_PREFIX`       | `attribute.node.policydriven.unimi.it` | Prefix for input attribute labels  |
| `PROPERTY_PREFIX`        | `property.node.policydriven.unimi.it`  | Prefix for output property labels  |
| `LOG_LEVEL`              | `INFO`                                 | One of DEBUG, INFO, WARNING, ERROR |

## Running locally

Requires Python 3.12+, a working `kubectl` context and the CRD already applied.

```bash
pip install -r requirements.txt
kopf run main.py
```

## Deploying to Kubernetes

For `kind` environments, the entire deployment lifecycle is fully automated by the `init-cluster.sh` script. 

To update the node-property-controller manually:

```bash
# Build the image and load it into the cluster 
docker build -t node-property-controller:latest .
kind load docker-image node-property-controller:latest --name <cluster-name>

# Namespace, RBAC, network policy, deployment
kubectl apply -f k8s/rbac.yaml
kubectl apply -f k8s/network-policy.yaml
kubectl apply -f k8s/deployment.yaml

# Wait for the service to be fully rolled out and ready
kubectl -n node-property-controller rollout status deployment/node-property-controller --timeout=180s
```

## Testing

```bash
pip install pytest pytest-cov
pytest -v --cov=src
```
