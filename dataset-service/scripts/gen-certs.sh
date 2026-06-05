#!/usr/bin/env bash
# Generates a self-signed CA + server cert for the dataset service, creates the
# TLS secret (cert+key+ca.crt) and prints the base64 CA bundle for provider.yaml.

export MSYS_NO_PATHCONV=1

set -euo pipefail

readonly DIR="${1:-.certs}"
readonly TARGET_ENV="${TARGET_ENV:-local}"
readonly TARGET_DIR="${DIR}/${TARGET_ENV}"
readonly SVC="${SVC:-dataset-service}" 
readonly NS="${NS:-dataset-service}" 
readonly CN="${SVC}.${NS}.svc"
readonly PROVIDER_FILE="k8s/provider.yaml"

mkdir -p "$TARGET_DIR"

echo "Generating self-signed CA and server cert for ${CN} (Env: ${TARGET_ENV})..."
openssl req -x509 -newkey rsa:4096 -nodes \
  -keyout "$TARGET_DIR/ca.key" -out "$TARGET_DIR/ca.crt" -days 365 \
  -subj "/CN=${SVC}-ca" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign"

echo "Generating server key and CSR..."
openssl req -newkey rsa:4096 -nodes \
  -keyout "$TARGET_DIR/tls.key" -out "$TARGET_DIR/tls.csr" -subj "/CN=${CN}"

if [[ "$TARGET_ENV" == "local" ]]; then
  echo "Setting SAN for local development..."
  cat > "$TARGET_DIR/san.cnf" <<SAN
subjectAltName=IP:127.0.0.1,DNS:localhost
SAN
else
  echo "Setting SAN for Kubernetes cluster..."
  cat > "$TARGET_DIR/san.cnf" <<SAN
subjectAltName=DNS:${SVC}.${NS}.svc,DNS:${SVC}.${NS}.svc.cluster.local
SAN
fi

echo "Signing server cert with CA..."
openssl x509 -req -in "$TARGET_DIR/tls.csr" \
  -CA "$TARGET_DIR/ca.crt" -CAkey "$TARGET_DIR/ca.key" -CAcreateserial \
  -out "$TARGET_DIR/tls.crt" -days 365 -extfile "$TARGET_DIR/san.cnf"

CA_B64=$(base64 -w0 "$TARGET_DIR/ca.crt")

# Update the gatekeeper provider for external data with the 
# new CA bundle if we're in a k8s environment
if [[ "$TARGET_ENV" == "k8s" ]]; then
  CA_B64=$(base64 -w0 "$TARGET_DIR/ca.crt")
  
  if [ -f "$PROVIDER_FILE" ]; then
    echo "Updating $PROVIDER_FILE with the new caBundle..."
    sed -i -E "s|([ ]*caBundle:).*|\1 ${CA_B64}|" "$PROVIDER_FILE"
    echo "Updated $PROVIDER_FILE with the new CA bundle."
  else
    echo "Error: $PROVIDER_FILE not found, cannot inject caBundle." >&2
    exit 1
  fi
else
  echo "Generated CA bundle (base64):"
  echo "$CA_B64"
fi