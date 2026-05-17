# Node Property Operator

Kubernetes operator that classifies cluster nodes against property definitions (`NodePropertyDefinition` CRD) and writes the resulting levels as node labels.

For each node `n` and each property `p`, the operator computes the highest level whose DNF expression is satisfied by the node's attribute labels, then labels the node with:

```
property.node.thesis.io/<p> = <level>
```

---

## Architecture

The controller watches two kinds of objects:

- `NodePropertyDefinition` CRDs (group `thesis.io`)
- `Node` resources

Whenever either changes, the affected nodes are re-evaluated and their property labels updated.

---

## Configuration

All configurable via environment variables (with defaults):

| Variable             | Default                       | Description                          |
|----------------------|-------------------------------|--------------------------------------|
| `GROUP`              | `thesis.io`                   | CRD API group                        |
| `VERSION`            | `v1alpha1`                    | CRD API version                      |
| `PLURAL`             | `node-property-definitions`   | CRD plural name                      |
| `ATTRIBUTE_PREFIX`   | `attribute.node.thesis.io`    | Prefix for input attribute labels    |
| `PROPERTY_PREFIX`    | `property.node.thesis.io`     | Prefix for output property labels    |
| `LOG_LEVEL`          | `INFO`                        | One of DEBUG, INFO, WARNING, ERROR   |
| `LIVENESS_ENDPOINT`  | `http://0.0.0.0:9090/healthz` | Liveness endpoint URL                |

---

## Running locally

Requires Python 3.12+, a working `kubectl` context and the CRD already applied.

```bash
pip install -r requirements.txt
kopf run main.py
```

---

## Deploying to Kubernetes

### Build and load the image

For `kind`:

```bash
docker build -t node-property-operator:latest .
kind load docker-image node-property-operator:latest --name <cluster-name>
```

### Apply manifests

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/rbac.yaml
kubectl apply -f k8s/deployment.yaml
```

### Verify

```bash
kubectl -n node-property-operator get pods
kubectl -n node-property-operator logs -l app.kubernetes.io/name=node-property-operator -f
kubectl get nodes --show-labels
```

---

## Testing

```bash
pytest -v
```
