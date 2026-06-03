#!/usr/bin/env bash
# Generates a self-signed CA + server cert for the dataset service, creates the
# TLS secret (cert+key+ca.crt) and prints the base64 CA bundle for provider.yaml.

export MSYS_NO_PATHCONV=1

set -euo pipefail

readonly DIR=".certs"
readonly SVC="dataset-service" 
readonly NS="dataset-service" 
readonly CN="${SVC}.${NS}.svc"
readonly PROVIDER_FILE="k8s/provider.yaml"

mkdir -p "$DIR"

echo "Generating self-signed CA and server cert for ${CN}..."
openssl req -x509 -newkey rsa:4096 -nodes \
  -keyout "$DIR/ca.key" -out "$DIR/ca.crt" -days 365 -subj "/CN=dataset-service-ca"

echo "Generating server key and CSR..."
openssl req -newkey rsa:4096 -nodes \
  -keyout "$DIR/tls.key" -out "$DIR/tls.csr" -subj "/CN=${CN}"

cat > "$DIR/san.cnf" <<SAN
subjectAltName=DNS:${SVC}.${NS}.svc,DNS:${SVC}.${NS}.svc.cluster.local
SAN

echo "Signing server cert with CA..."
openssl x509 -req -in "$DIR/tls.csr" \
  -CA "$DIR/ca.crt" -CAkey "$DIR/ca.key" -CAcreateserial \
  -out "$DIR/tls.crt" -days 365 -extfile "$DIR/san.cnf"

echo "Creating TLS secret in Kubernetes..."
kubectl create secret generic dataset-service-tls \
  --from-file=ca.crt="$DIR/ca.crt" \
  --from-file=tls.crt="$DIR/tls.crt" \
  --from-file=tls.key="$DIR/tls.key" \
  -n "$NS" --dry-run=client -o yaml | kubectl apply -f -

CA_B64=$(base64 -w0 "$DIR/ca.crt")

# Check if provider.yaml exists and contains "caBundle:" 
# and, if so, replace the value with the new base64 CA bundle.
if [ -f "$PROVIDER_FILE" ]; then
  echo "Updating $PROVIDER_FILE with the new caBundle..."
  sed -i -E "s|([ ]*caBundle:).*|\1 ${CA_B64}|" "$PROVIDER_FILE"
  echo "Updated $PROVIDER_FILE with the new CA bundle."
else
  echo "Warning: $PROVIDER_FILE not found. Please update it manually with the following CA bundle:"
  echo "Paste manually into k8s/provider.yaml under spec.caBundle:"
  echo "----------------------------------------------------------------"
  echo "$CA_B64"
  echo "----------------------------------------------------------------"
fi
