#!/usr/bin/env bash
#
# Generates a self-signed CA and a server certificate for the dataset-service,
# creates the TLS secret in the cluster, and prints the base64 CA bundle to
# paste into k8s/provider.yaml (spec.caBundle).
#
# Gatekeeper External Data requires the provider to be served over TLS and
# validates its certificate against the CA bundle declared in the Provider CR.

set -euo pipefail

readonly SVC="dataset-service"
readonly NS="dataset-service"
readonly DIR="certs"
readonly CN="${SVC}.${NS}.svc"

mkdir -p "$DIR"

# 1. CA
openssl req -x509 -newkey rsa:4096 -nodes \
    -keyout "$DIR/ca.key" -out "$DIR/ca.crt" \
    -days 365 -subj "/CN=dataset-service-ca"

# 2. Server key + CSR
openssl req -newkey rsa:4096 -nodes \
    -keyout "$DIR/tls.key" -out "$DIR/tls.csr" \
    -subj "/CN=${CN}"

# 3. Sign server cert with SAN matching the in-cluster DNS name
cat > "$DIR/san.cnf" <<EOF
subjectAltName=DNS:${SVC}.${NS}.svc,DNS:${SVC}.${NS}.svc.cluster.local
EOF

openssl x509 -req -in "$DIR/tls.csr" \
    -CA "$DIR/ca.crt" -CAkey "$DIR/ca.key" -CAcreateserial \
    -out "$DIR/tls.crt" -days 365 -extfile "$DIR/san.cnf"

# 4. Create/replace the TLS secret in the cluster
kubectl create secret tls dataset-service-tls \
    --cert="$DIR/tls.crt" --key="$DIR/tls.key" \
    -n "$NS" --dry-run=client -o yaml | kubectl apply -f -

# 5. Print the CA bundle for the Provider CR
echo
echo "Paste the following into k8s/provider.yaml under spec.caBundle:"
echo "----------------------------------------------------------------"
base64 -w0 "$DIR/ca.crt"
echo
echo "----------------------------------------------------------------"
