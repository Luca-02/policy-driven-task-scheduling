# Dataset Service (mock data governator)

Mock service that simulates a data governator (à la Apache Atlas) for the policy-driven task scheduling system. It stores dataset **metadata** — the protection class `β(d)` (`requirements`) and the current placement `λ(d)` (`nodes`) — and exposes them to OPA Gatekeeper through the **External Data Provider** protocol, plus a small CRUD API for tests and demos.

It is backed by **TinyDB**: a single human-readable JSON file, trivial to inspect and edit during a demo, with a proper CRUD API on top.

---

## Endpoints

| Method | Path               | Audience         | Description                       |
| ------ | ------------------ | ---------------- | --------------------------------- |
| GET    | `/healthz`         | k8s probes       | liveness/readiness                |
| POST   | `/validate`        | Gatekeeper (EDP) | resolves dataset metadata by name |
| GET    | `/datasets`        | admin/debug      | list all datasets                 |
| GET    | `/datasets/{name}` | admin/debug      | single dataset detail             |
| POST   | `/datasets`        | admin            | create dataset                    |
| PUT    | `/datasets/{name}` | admin            | full replace of dataset metadata  |
| DELETE | `/datasets/{name}` | admin            | delete dataset                    |

### Dataset metadata

```json
{
  "name": "d1",
  "requirements": { "security": 2, "computation": 1 },
  "nodes": ["kind-worker", "kind-worker2"],
  "owner": "org-a",
  "category": "medical"
}
```

`requirements` is `β(d)`, `nodes` is `λ(d)`. `owner` and `category` are stored but **not yet enforced** — reserved for future Chinese Wall and per-category subscription limits.

### EDP `/validate`

Request (sent by Gatekeeper):

```json
{ "apiVersion": "externaldata.gatekeeper.sh/v1beta1",
  "kind": "ProviderRequest",
  "request": { "keys": ["d1", "d2"] } }
```

Response: one item per key, carrying either the metadata (`value`) or a per-key `error` if the dataset is unknown. OPA then denies the TaskRequest if any item has a non-empty error.

---

## Configuration (env vars)

| Variable    | Default               | Description                      |
| ----------- | --------------------- | -------------------------------- |
| `DB_PATH`   | `/data/datasets.json` | TinyDB JSON file                 |
| `SEED_PATH` | `/app/seed.json`      | seed data, applied only if empty |
| `PORT`      | `8443`                | HTTPS port                       |
| `LOG_LEVEL` | `INFO`                | DEBUG/INFO/WARNING/ERROR         |

---

## Testing

```bash
pip install -r requirements.txt httpx pytest
pytest -v
```

---

## Deploying to Kubernetes (kind)

Gatekeeper External Data requires (1) the feature flag enabled and (2) the provider served over TLS.

### 1. Enable external data in Gatekeeper

```bash
kubectl -n gatekeeper-system patch deployment gatekeeper-controller-manager \
  --type='json' -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--enable-external-data=true"}]'
kubectl -n gatekeeper-system patch deployment gatekeeper-audit \
  --type='json' -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--enable-external-data=true"}]'
```

### 2. Build and load the image

```bash
docker build -t dataset-service:latest .
kind load docker-image dataset-service:latest --name <cluster-name>
```

### 3. Namespace + TLS certs + manifests

```bash
kubectl apply -f k8s/namespace.yaml
bash scripts/gen-certs.sh          # creates the TLS secret, prints the CA bundle
# paste the printed CA bundle into k8s/provider.yaml (spec.caBundle)
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/provider.yaml
```

### 4. Apply the dataset validation policy

```bash
kubectl apply -f ../k8s/policy/validate-task-request-datasets-template.yaml
kubectl apply -f ../k8s/policy/validate-task-request-datasets-constraint.yaml
```

Now applying a `TaskRequest` referencing an unknown dataset is rejected at admission; one referencing only known datasets is admitted and proceeds to the TaskRequest controller.
