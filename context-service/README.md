# Context Service (mock issuer & context-conflict authority)

Mock service holding the two pieces of the Chinese Wall model that live
outside the cluster's Kubernetes-native objects: issuer authorizations
`auth(i)` and the context conflict-of-interest relation `X_conf`. Exposes
them to OPA Gatekeeper via the **External Data Provider** protocol (issuer
existence and `auth(i)`, consumed by the `c_auth` admission constraint),
plus a CRUD API used to manage both.

Like `dataset-service`, this is intentionally a thin demo component, not a
production system: no authentication is enforced. Isolation is provided by
the ClusterIP scope and a `NetworkPolicy` restricting ingress to Gatekeeper,
the scheduler, `dataset-service` (which calls `/conflicts` to validate
`ctx(d)`) and the Context Service namespace itself. TLS is kept because
Gatekeeper External Data requires the provider to be served over TLS.

## Architecture choices

- **PostgreSQL via CloudNativePG**: same as `dataset-service`, the service
  connects to the `-rw` service so writes always reach the current primary.
- **A single service for `auth` and `X_conf`, not two**: they are the same
  domain (identity/security policy) and, more importantly, the
  well-formedness invariant below spans both, so keeping them in the same
  database lets it be enforced with a local transaction instead of a
  distributed one.
- **Concurrency**: every write that can affect the invariant

  ```
  (auth(i) x auth(i)) ∩ X_conf = ∅   for every i in I
  ```

  (assigning/updating an issuer's contexts, or declaring a new conflict)
  serializes against every other such write via a row lock on a sentinel
  row (`ContextRepository._acquire_lock`), preventing the write-skew
  anomaly where two concurrent, individually "safe" writes leave the
  invariant broken. See the docstring on that method for details. This is
  only load-bearing on PostgreSQL; on SQLite (tests, local dev) writes are
  already serialized by the shared single connection.
- **Symmetric checks, one direction out of scope**: creating/updating an
  issuer is checked against existing conflicts, and creating a conflict is
  checked against existing issuers — both enforced transactionally since
  they live in the same database. The equivalent check for datasets
  (`(ctx(d) x ctx(d)) ∩ X_conf = ∅`) lives in `dataset-service`, a
  different service: only the "new dataset against existing conflicts"
  direction is enforced there (a synchronous HTTP call at write time); a
  new conflict retroactively invalidating an existing dataset's contexts is
  *not* checked. This is a deliberate scope cut for the prototype,
  documented as an assumption: conflict configuration precedes dataset
  population.

## Endpoints

| Method | Path                        | Description                          |
| ------ | --------------------------- | ------------------------------------ |
| GET    | `/healthz`                  | liveness/readiness                   |
| POST   | `/validate`                 | Gatekeeper EDP (issuer existence + `auth(i)`) |
| GET    | `/issuers`                  | list issuers                         |
| GET    | `/issuers/{name}`           | issuer detail                        |
| POST   | `/issuers/query`            | query issuers                        |
| POST   | `/issuers`                  | create issuer                        |
| POST   | `/issuers/batch`            | create multiple issuers (atomic)     |
| PUT    | `/issuers/{name}`           | full replace issuer (debug only)     |
| DELETE | `/issuers/{name}`           | delete issuer                        |
| DELETE | `/issuers`                  | delete all issuers (debug only)      |
| GET    | `/conflicts`                | list context conflicts (`X_conf`)    |
| POST   | `/conflicts`                | create a conflict pair               |
| DELETE | `/conflicts/{a}/{b}`        | delete a conflict pair               |
| DELETE | `/conflicts`                | delete all conflicts (debug only)    |

Writes to `/issuers*` and `/conflicts` that would violate the
well-formedness invariant return `409 Conflict` with a `detail` payload
naming the offending pairs or issuers.

## Configuration (env vars)

| Variable                 | Default                              | Description               |
| ------------------------ | ------------------------------------ | ------------------------- |
| `DB_URL`                 | `sqlite://`                          | SQLAlchemy connection URI |
| `HOST`                   | `127.0.0.1`                          | listen host               |
| `PORT`                   | `8443`                               | listen port               |
| `TLS_CERT_FILE`          | (unset)                              | server cert (enables TLS) |
| `TLS_KEY_FILE`           | (unset)                              | server key (enables TLS)  |
| `LOG_LEVEL`              | `INFO`                               | DEBUG/INFO/WARNING/ERROR  |

When `TLS_CERT_FILE` / `TLS_KEY_FILE` are unset, the service runs in plain
HTTP (used by tests).

## Running locally

Requires Python 3.12+.

```bash
pip install -r requirements.txt
python main.py
```

## Deploying to Kubernetes

### 1. Database Prerequisites

Reuses the CloudNativePG operator already installed for `dataset-service`.

```bash
kubectl apply -f k8s/postgres-cluster.yaml
kubectl wait -n context-service --for=condition=Ready cluster/context-db --timeout=600s
```

### 2. Certificates & App Deployment

```bash
# From this directory (context-service/); gen-certs.sh is shared at the repo root
SVC="context-service" NS="context-service" TARGET_ENV="k8s" bash ../scripts/gen-certs.sh

# Create the TLS Secret for the service
kubectl create secret generic context-service-tls \
    --from-file=ca.crt=".certs/k8s/ca.crt" \
    --from-file=tls.crt=".certs/k8s/tls.crt" \
    --from-file=tls.key=".certs/k8s/tls.key" \
    -n context-service

# Build and load the image into Kind
docker build -t context-service:latest .
kind load docker-image context-service:latest --name <cluster-name>

# Apply all service manifests
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/network-policy.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/provider.yaml

kubectl -n context-service rollout status deployment/context-service --timeout=180s
```

> **Nota:** `dataset-service`'s own `NetworkPolicy` deve essere aggiornato
> per permettere l'egress verso `context-service:8443` (serve alla
> validazione di `ctx(d)` sulla POST/PUT dei dataset) — non incluso in
> questo servizio, va aggiornato nel manifest di `dataset-service`.

## Testing

```bash
pip install pytest pytest-cov
pytest -v --cov=src
```

Tests need **no external services**: the repository is tested on in-memory
SQLite (where the concurrency lock is a documented no-op, see
Architecture choices above).
