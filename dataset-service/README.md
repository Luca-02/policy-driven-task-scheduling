# Dataset Service (mock data governator)

Mock service simulating a data governator (à la Apache Atlas) for the policy-driven task scheduling system. Stores dataset **metadata** — the protection class `β(d)` (`requirements`), the size used for transfer cost (`sizeMB`) and the placement `λ(d)` (`nodes`) — and exposes them to OPA Gatekeeper via the **External Data Provider** protocol, plus a CRUD API.

The service is intentionally a thin demo component, not a production system: no authentication is enforced. Isolation is provided by the ClusterIP scope and a `NetworkPolicy` that restricts ingress to the namespaces of Gatekeeper and the TaskRequest controller. TLS is kept because Gatekeeper External Data requires the provider to be served over TLS.

## Architecture choices

- **PostgreSQL in HA via CloudNativePG**: a `Cluster` of 1 primary + 2 replicas with automatic failover. The service connects to the `-rw` service, so writes always reach the current primary; on failover SQLAlchemy reconnects via `pool_pre_ping`.
- **Replicable service**: state lives only in PostgreSQL, so the Deployment runs multiple replicas without coordination.

## Endpoints

| Method | Path               | Description                      |
| ------ | ------------------ | -------------------------------- |
| GET    | `/healthz`         | liveness/readiness               |
| POST   | `/validate`        | Gatekeeper EDP: resolve metadata |
| GET    | `/datasets`        | list datasets                    |
| GET    | `/datasets/{name}` | dataset detail                   |
| POST   | `/datasets`        | create                           |
| PUT    | `/datasets/{name}` | full replace                     |
| DELETE | `/datasets/{name}` | delete                           |

## Configuration (env vars)

| Variable                 | Default                              | Description               |
| ------------------------ | ------------------------------------ | ------------------------- |
| `DB_URL`                 | `sqlite://`                          | SQLAlchemy connection URI |
| `HOST`                   | `0.0.0.0`                            | listen host               |
| `PORT`                   | `8443`                               | listen port               |
| `TLS_CERT_FILE`          | (unset)                              | server cert (enables TLS) |
| `TLS_KEY_FILE`           | (unset)                              | server key (enables TLS)  |
| `GATEKEEPER_API_VERSION` | `externaldata.gatekeeper.sh/v1beta1` | API version for EDP       |
| `LOG_LEVEL`              | `INFO`                               | DEBUG/INFO/WARNING/ERROR  |

When `TLS_CERT_FILE` / `TLS_KEY_FILE` are unset, the service runs in plain HTTP (used by tests). In the cluster both are set, so TLS is on.

## Running locally

Requires Python 3.12+.

```bash
pip install -r requirements.txt
python main.py
```

## Deploying to Kubernetes

For `kind`:

```bash
# install the CloudNativePG operator
kubectl apply --server-side -f https://raw.githubusercontent.com/cloudnative-pg/cloudnative-pg/release-1.29/releases/cnpg-1.29.1.yaml

# # enable external data in Gatekeeper (controller-manager + audit)
# kubectl -n gatekeeper-system patch deployment gatekeeper-controller-manager \
#   --type='json' -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--enable-external-data=true"}]'

# build + load image
docker build -t dataset-service:latest .
kind load docker-image dataset-service:latest --name <cluster-name>

# deploy the postgres cluster
kubectl apply -f k8s/postgres-cluster.yaml  # wait until the Cluster is ready

# generate TLS certs for the service
bash gen-certs.sh

# paste the CA bundle into k8s/provider.yaml (spec.caBundle)
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/network-policy.yaml
kubectl apply -f k8s/provider.yaml
kubectl apply -f k8s/deployment.yaml
```

## Testing

```bash
pip install pytest pytest-cov
pytest -v --cov=src
```

Tests need **no external services**: the repository is exercised on in-memory SQLite.
