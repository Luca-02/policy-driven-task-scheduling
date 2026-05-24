#!/usr/bin/env bash

set -euo pipefail

#######################################
# Configuration
#######################################

readonly CLUSTER_NAME="thesis"
readonly CLUSTER_CONFIG_FILE="k8s/cluster-config.yaml"

readonly HEADLAMP_MANIFEST_URL="https://raw.githubusercontent.com/kinvolk/headlamp/main/kubernetes-headlamp.yaml"

readonly NODE_PROPERTY_CONTROLLER_PATH="node-property-controller"
readonly NODE_PROPERTY_CONTROLLER_IMAGE="node-property-controller:latest"

readonly NODE_PROPERTY_CONTROLLER_NAMESPACE_FILE="node-property-controller/k8s/namespace.yaml"
readonly NODE_PROPERTY_CONTROLLER_NETWORK_POLICY_FILE="node-property-controller/k8s/network-policy.yaml"
readonly NODE_PROPERTY_CONTROLLER_RBAC_FILE="node-property-controller/k8s/rbac.yaml"
readonly NODE_PROPERTY_CONTROLLER_DEPLOYMENT_FILE="node-property-controller/k8s/deployment.yaml"

readonly NODE_PROPERTY_CONTROLLER_NAMESPACE="node-property-controller"
readonly NODE_PROPERTY_CONTROLLER_DEPLOYMENT="node-property-controller"

readonly NODE_PROPERTY_FILES=(
    "node-property/security-node-property.yaml"
    "node-property/computation-node-property.yaml"
)

#######################################
# Logging
#######################################

log() {
    printf "\n[%s] %s\n" "$(date '+%H:%M:%S')" "$*"
}

warn() {
    printf "\n[WARN] %s\n" "$*" >&2
}

error() {
    printf "\n[ERROR] %s\n" "$*" >&2
}

#######################################
# Error handling
#######################################

cleanup() {
    local exit_code=$?

    if [[ $exit_code -ne 0 ]]; then
        error "Script failed with exit code $exit_code"
    fi
}

trap cleanup EXIT

#######################################
# Utilities
#######################################

cmd_exists() {
    command -v "$1" >/dev/null 2>&1
}

require_cmd() {
    local cmd="$1"

    if ! cmd_exists "$cmd"; then
        error "'$cmd' is not installed or not in PATH."
        exit 1
    fi
}

resource_exists() {
    kubectl "$@" >/dev/null 2>&1
}

#######################################
# Preconditions
#######################################

log "k8s-init: starting cluster setup"

require_cmd kind
require_cmd kubectl

#######################################
# Create cluster
#######################################

if kind get clusters | grep -qx "$CLUSTER_NAME"; then
    log "Kind cluster '$CLUSTER_NAME' already exists"
else
    log "Creating kind cluster '$CLUSTER_NAME' using config '$CLUSTER_CONFIG_FILE'"

    kind create cluster \
        --name "$CLUSTER_NAME" \
        --config "$CLUSTER_CONFIG_FILE"
fi

#######################################
# Ensure kubectl context
#######################################

EXPECTED_CONTEXT="kind-${CLUSTER_NAME}"
CURRENT_CONTEXT="$(kubectl config current-context)"

if [[ "$CURRENT_CONTEXT" != "$EXPECTED_CONTEXT" ]]; then
    log "Switching kubectl context to '$EXPECTED_CONTEXT'"

    kubectl config use-context "$EXPECTED_CONTEXT"
fi

#######################################
# Install Headlamp
#######################################

log "Installing Headlamp dashboard"

if ! kubectl apply -f "$HEADLAMP_MANIFEST_URL"; then
    warn "Failed to apply Headlamp manifest"
fi

#######################################
# Headlamp RBAC
#######################################

log "Ensuring Headlamp admin service account"

if ! resource_exists -n kube-system get serviceaccount headlamp-admin; then
    kubectl -n kube-system create serviceaccount headlamp-admin

    log "Created ServiceAccount kube-system/headlamp-admin"
else
    log "ServiceAccount already exists"
fi

if ! resource_exists get clusterrolebinding headlamp-admin; then
    kubectl create clusterrolebinding headlamp-admin \
        --serviceaccount=kube-system:headlamp-admin \
        --clusterrole=cluster-admin

    log "Created ClusterRoleBinding headlamp-admin"
else
    log "ClusterRoleBinding already exists"
fi

#######################################
# CRDs
#######################################

readonly NODE_PROPERTY_DEFINITIONS_CRD_FILE="node-property/node-property-definitions-crd.yaml"

log "Installing NodePropertyDefinition CRD"

kubectl apply -f "$NODE_PROPERTY_DEFINITIONS_CRD_FILE"

#######################################
# Load local Docker image into kind
#######################################

if cmd_exists docker; then
    if docker image inspect "$NODE_PROPERTY_CONTROLLER_IMAGE" >/dev/null 2>&1; then
        log "Docker image '$NODE_PROPERTY_CONTROLLER_IMAGE' already exists"
    else
        log "Docker image '$NODE_PROPERTY_CONTROLLER_IMAGE' not found, building..."

        if [[ ! -f "$NODE_PROPERTY_CONTROLLER_PATH/Dockerfile" ]]; then
            error "Dockerfile not found in $NODE_PROPERTY_CONTROLLER_PATH/"
            exit 1
        fi

        docker build -t "$NODE_PROPERTY_CONTROLLER_IMAGE" "$NODE_PROPERTY_CONTROLLER_PATH/"
    fi

    log "Loading image '$NODE_PROPERTY_CONTROLLER_IMAGE' into kind cluster"

    kind load docker-image \
        "$NODE_PROPERTY_CONTROLLER_IMAGE" \
        --name "$CLUSTER_NAME"
else
    warn "Docker not available, skipping build and load"
fi

#######################################
# Controller deployment
#######################################

log "Deploying node-property-controller"

kubectl apply -f "$NODE_PROPERTY_CONTROLLER_NAMESPACE_FILE"
kubectl apply -f "$NODE_PROPERTY_CONTROLLER_NETWORK_POLICY_FILE"
kubectl apply -f "$NODE_PROPERTY_CONTROLLER_RBAC_FILE"
kubectl apply -f "$NODE_PROPERTY_CONTROLLER_DEPLOYMENT_FILE"

#######################################
# Wait for rollout
#######################################

log "Waiting for deployment rollout"

if ! kubectl -n "$NODE_PROPERTY_CONTROLLER_NAMESPACE" \
    rollout status deployment/"$NODE_PROPERTY_CONTROLLER_DEPLOYMENT" \
    --timeout=180s; then

    warn "Deployment did not become ready within timeout"

    log "Dumping pod status for debugging"
    kubectl -n "$NODE_PROPERTY_CONTROLLER_NAMESPACE" get pods -o wide || true

    log "Recent logs"
    kubectl -n "$NODE_PROPERTY_CONTROLLER_NAMESPACE" logs \
        deployment/"$NODE_PROPERTY_CONTROLLER_DEPLOYMENT" \
        --tail=100 || true
fi

#######################################
# Apply node properties
#######################################

log "Applying concrete node properties"

for property_file in "${NODE_PROPERTY_FILES[@]}"; do
    log "Applying node property: $property_file"

    kubectl apply -f "$property_file"
done

#######################################
# Summary
#######################################

log "Cluster information"

kubectl get nodes -o wide

log "Installed namespaces"

kubectl get ns

log "k8s-init: completed successfully!"
