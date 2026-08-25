# Node Controller

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

Node sanitization (Algorithm `Sanitize(n)`) is implemented in `src/sanitization.py` as a standalone `Sanitizer`, independent of `Controller`. The controller's periodic timer (`main.py`) delegates to it on every tick, and the same class backs the manual sanitization Job below.

## Configuration

All configurable via environment variables (with defaults):

| Variable                 | Default                                | Description                        |
| ------------------------ | -------------------------------------- | ---------------------------------- |
| `GROUP`                  | `policydriven.unimi.it`                | CRD API group                      |
| `VERSION`                | `v1alpha1`                             | CRD API version                    |
| `NODE_PROPERTIES_PLURAL` | `nodeproperties`                       | CRD NodeProperties plural name     |
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

To update the node-controller manually:

```bash
# Build the image and load it into the cluster 
docker build -t node-controller:latest .
kind load docker-image node-controller:latest --name <cluster-name>

# Namespace, RBAC, network policy, deployment
kubectl apply -f k8s/rbac.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/network-policy.yaml

# Wait for the service to be fully rolled out and ready
kubectl -n node-controller rollout status deployment/node-controller --timeout=180s
```

## Manual node sanitization

For testing or troubleshooting, every node can be sanitized on demand without waiting for the periodic timer, by running `sanitize.py` as a one-off Kubernetes Job. It runs the exact same `Sanitize(n)` logic used by the controller, once, for each node in the cluster (control-plane nodes are skipped, same as the timer).

```bash
kubectl apply -f k8s/sanitize.yaml
kubectl -n node-controller logs job/node-sanitize-manual
```

Note that `Sanitize(n)` is not a blocking wait: for a node that still has active Pods scheduled by our scheduler, the Job applies the sanitizing taint and moves on without clearing that node's `Lambda(n)` — rerun the Job (`kubectl delete job node-sanitize-manual` first, Job names aren't reusable) once those Pods have completed.

## Testing

```bash
pip install pytest pytest-cov
pytest -v --cov=src
```
