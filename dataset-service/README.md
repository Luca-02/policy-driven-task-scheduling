# Dataset Service (mock data governator)

Mock service simulating a data governator (à la Apache Atlas) for the policy-driven task scheduling system. Stores dataset **metadata** — the protection class `β(d)` (`requirements`), the size used for transfer cost (`sizeMB`) and the placement `λ(d)` (`nodes`) — and exposes them to OPA Gatekeeper via the **External Data Provider** protocol, plus a CRUD API.

The service is intentionally a thin demo component, not a production system: no authentication is enforced. Isolation is provided by the ClusterIP scope and a `NetworkPolicy` that restricts ingress to the namespaces of Gatekeeper and the TaskRequest controller. TLS is kept because Gatekeeper External Data requires the provider to be served over TLS.

## Architecture choices

- **PostgreSQL in HA via CloudNativePG**: PostgreSQL `Cluster`. The service connects to the `-rw` service, so writes always reach the current primary.
- **Replicable service**: state lives only in PostgreSQL, so the Deployment could runs multiple replicas without coordination.

## Endpoints

| Method | Path               | Description              |
| ------ | ------------------ | ------------------------ |
| GET    | `/healthz`         | liveness/readiness       |
| POST   | `/validate`        | Gatekeeper EDP           |
| GET    | `/datasets`        | list datasets            |
| GET    | `/datasets/{name}` | dataset detail           |
| POST   | `/datasets`        | create dataset           |
| POST   | `/datasets/batch`  | create multiple datasets |
| PUT    | `/datasets/{name}` | full replace dataset     |
| DELETE | `/datasets/{name}` | delete dataset           |
| DELETE | `/datasets/`       | delete all datasets      |

## Configuration (env vars)

| Variable                 | Default                              | Description               |
| ------------------------ | ------------------------------------ | ------------------------- |
| `DB_URL`                 | `sqlite://`                          | SQLAlchemy connection URI |
| `HOST`                   | `127.0.0.1`                          | listen host               |
| `PORT`                   | `8443`                               | listen port               |
| `TLS_CERT_FILE`          | (unset)                              | server cert (enables TLS) |
| `TLS_KEY_FILE`           | (unset)                              | server key (enables TLS)  |
| `GATEKEEPER_API_VERSION` | `externaldata.gatekeeper.sh/v1beta1` | API version for EDP       |
| `LOG_LEVEL`              | `INFO`                               | DEBUG/INFO/WARNING/ERROR  |

When `TLS_CERT_FILE` / `TLS_KEY_FILE` are unset, the service runs in plain HTTP (used by tests). 

## Running locally

Requires Python 3.12+.

```bash
pip install -r requirements.txt
python main.py
```

## Deploying to Kubernetes

For `kind` environments, the entire deployment lifecycle is fully automated by the `init-cluster.sh` script. 

To update the dataset-service manually:

### 1. Database Prerequisites

The service requires the CloudNativePG operator and a running PostgreSQL cluster.

```bash
# Install the CloudNativePG operator
kubectl apply --server-side -f https://raw.githubusercontent.com/cloudnative-pg/cloudnative-pg/release-1.29/releases/cnpg-1.29.1.yaml

# Deploy the highly-available postgres cluster
kubectl apply -f k8s/postgres-cluster.yaml

# Wait until the Cluster is ready to accept connections (can take a few times)
kubectl wait -n dataset-service --for=condition=Ready cluster/dataset-db --timeout=600s
```

### 2. Certificates & App Deployment

The `gen-certs.sh`, if executed with the env `TARGET_ENV=k8s`, automatically generates a self-signed CA, creates the server certificates, and automatically injects the base64 CA bundle into k8s/provider.yaml.
```bash
# Generate TLS certs and update provider.yaml
TARGET_ENV="k8s" bash scripts/gen-certs.sh

# Create the TLS Secret for the service
kubectl create secret generic dataset-service-tls \
    --from-file=ca.crt=".certs/k8s/ca.crt" \
    --from-file=tls.crt=".certs/k8s/tls.crt" \
    --from-file=tls.key=".certs/k8s/tls.key" \
    -n dataset-service

# Build and load the image into Kind
docker build -t dataset-service:latest .
kind load docker-image dataset-service:latest --name <cluster-name>

# Apply all service manifests
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/network-policy.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/provider.yaml

# Wait for the service to be fully rolled out and ready
kubectl -n dataset-service rollout status deployment/dataset-service --timeout=180s
```

<!-- TODO: Add the seeding section procedure -->

## Testing

```bash
pip install pytest pytest-cov
pytest -v --cov=src
```

Tests need **no external services**: the repository is exercised on in-memory SQLite.
