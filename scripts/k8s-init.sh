#!/usr/bin/env bash

set -euo pipefail

echo "== k8s-init: starting cluster setup =="

cmd_exists() {
	command -v "$1" >/dev/null 2>&1
}

# Check for required tools: kind and kubectl
if ! cmd_exists kind; then
	echo "ERROR: 'kind' is not installed or not in PATH." >&2
	exit 1
fi
if ! cmd_exists kubectl; then
	echo "ERROR: 'kubectl' is not installed or not in PATH." >&2
	exit 1
fi

# Create kind cluster only if none exist
if [ -z "$(kind get clusters)" ]; then
	echo "No kind cluster found: creating cluster using k8s/cluster-config.yaml..."
	kind create cluster --config k8s/cluster-config.yaml
else
	echo "Found existing kind cluster:"
	kind get clusters
	echo "Skipping cluster creation."
fi

echo
echo "=== Installing Headlamp dashboard (idempotent) ==="
kubectl apply -f https://raw.githubusercontent.com/kinvolk/headlamp/main/kubernetes-headlamp.yaml || {
	echo "Warning: failed to apply Headlamp manifest." >&2
}

echo
echo "=== Ensuring Headlamp service account and clusterrolebinding ==="
if ! kubectl -n kube-system get serviceaccount headlamp-admin >/dev/null 2>&1; then
	kubectl -n kube-system create serviceaccount headlamp-admin
	echo "Created serviceaccount kube-system/headlamp-admin"
else
	echo "ServiceAccount kube-system/headlamp-admin already exists, skipping"
fi

if ! kubectl get clusterrolebinding headlamp-admin >/dev/null 2>&1; then
	kubectl create clusterrolebinding headlamp-admin --serviceaccount=kube-system:headlamp-admin --clusterrole=cluster-admin
	echo "Created clusterrolebinding headlamp-admin"
else
	echo "ClusterRoleBinding headlamp-admin already exists, skipping"
fi

echo
echo "=== Installing NodePropertyDefinition CRD ==="
kubectl apply -f node-property/node-property-definitions-crd.yaml

echo
echo "=== Deploying node-property-controller into cluster ==="
# Apply namespace and RBAC first
kubectl apply -f node-property-controller/k8s/namespace.yaml
kubectl apply -f node-property-controller/k8s/network-policy.yaml
kubectl apply -f node-property-controller/k8s/rbac.yaml

# If a local image named 'node-property-operator:latest' exists, load it into kind so pods can use it
if cmd_exists docker && docker image inspect node-property-operator:latest >/dev/null 2>&1; then
	echo "Local Docker image 'node-property-operator:latest' found: loading into kind cluster..."
	kind load docker-image node-property-operator:latest --name thesis
fi

# Apply deployment
kubectl apply -f node-property-controller/k8s/deployment.yaml

# Wait for the operator deployment to become ready
OP_NS=node-property-operator
OP_DEP=node-property-operator
echo "Waiting for deployment $OP_DEP in namespace $OP_NS to become ready..."
kubectl -n "$OP_NS" rollout status deployment/"$OP_DEP" --timeout=120s || {
	echo "Warning: operator deployment did not become ready within timeout." >&2
}

echo
echo "=== Applying concrete node properties ==="
kubectl apply -f node-property/security-node-property.yaml
kubectl apply -f node-property/computation-node-property.yaml

echo
echo "=== k8s-init: finished ==="
