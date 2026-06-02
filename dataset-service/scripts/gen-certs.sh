#!/usr/bin/env bash
# Generates a self-signed CA + server cert for the dataset service, creates the
# TLS secret (cert+key+ca.crt) and prints the base64 CA bundle for provider.yaml.

export MSYS_NO_PATHCONV=1

set -euo pipefail

readonly SVC="dataset-service" NS="dataset-service" DIR=".certs"
readonly CN="${SVC}.${NS}.svc"
mkdir -p "$DIR"

# CA
openssl req -x509 -newkey rsa:4096 -nodes \
  -keyout "$DIR/ca.key" -out "$DIR/ca.crt" -days 365 -subj "/CN=dataset-service-ca"

# Server key + CSR
openssl req -newkey rsa:4096 -nodes \
  -keyout "$DIR/tls.key" -out "$DIR/tls.csr" -subj "/CN=${CN}"

# Sign server cert with SAN matching the in-cluster DNS name
cat > "$DIR/san.cnf" <<SAN
subjectAltName=DNS:${SVC}.${NS}.svc,DNS:${SVC}.${NS}.svc.cluster.local
SAN

openssl x509 -req -in "$DIR/tls.csr" \
  -CA "$DIR/ca.crt" -CAkey "$DIR/ca.key" -CAcreateserial \
  -out "$DIR/tls.crt" -days 365 -extfile "$DIR/san.cnf"

# Secret carries cert, key and the CA
kubectl create secret generic dataset-service-tls \
  --from-file=tls.crt="$DIR/tls.crt" \
  --from-file=tls.key="$DIR/tls.key" \
  --from-file=ca.crt="$DIR/ca.crt" \
  -n "$NS" --dry-run=client -o yaml | kubectl apply -f -

# Print the CA bundle for the Provider CR
echo
echo "Paste into k8s/provider.yaml under spec.caBundle:"
echo "----------------------------------------------------------------"
base64 -w0 "$DIR/ca.crt"; echo
echo "----------------------------------------------------------------"
