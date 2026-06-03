#!/usr/bin/env bash
#
# Initializes the kind cluster:
# - Creates the cluster if it doesn't exist
# - Sets up kubectl context
# - Installs the Headlamp dashboard and creates an admin service account
# - Creates namespaces
# - Applies CRDs
# - Installs Gatekeeper and applies policy templates and constraints
# - Deploys the node-property-controller

set -euo pipefail

readonly CLUSTER_NAME="${CLUSTER_NAME:-kind}"

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

command_exist() {
    command -v "$1" >/dev/null 2>&1
}

resource_exists() {
    kubectl "$@" >/dev/null 2>&1
}

require_command() {
    local command="$1"

    if ! command_exist "$command"; then
        error "'$command' is not installed or not in PATH."
        exit 1
    fi
}

#######################################
# Preconditions
#######################################

log "k8s-init: starting cluster setup"

require_command kind
require_command kubectl

#######################################
# Create cluster
#######################################

readonly CLUSTER_CONFIG_FILE="k8s/cluster-config.yaml"

log "Checking for existing kind cluster '$CLUSTER_NAME'"
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
# Dashboard and tools
#######################################

readonly HEADLAMP_MANIFEST_URL="https://raw.githubusercontent.com/kinvolk/headlamp/main/kubernetes-headlamp.yaml"

log "Installing Headlamp"
if ! kubectl apply -f "$HEADLAMP_MANIFEST_URL"; then
    warn "Failed to apply Headlamp manifest"
fi

log "Ensuring Headlamp admin service account"
if ! resource_exists -n kube-system get serviceaccount headlamp-admin; then
    kubectl -n kube-system create serviceaccount headlamp-admin

    log "Created ServiceAccount kube-system/headlamp-admin"
else
    log "ServiceAccount already exists"
fi

log "Ensuring ClusterRoleBinding for Headlamp admin"
if ! resource_exists get clusterrolebinding headlamp-admin; then
    kubectl create clusterrolebinding headlamp-admin \
        --serviceaccount=kube-system:headlamp-admin \
        --clusterrole=cluster-admin

    log "Created ClusterRoleBinding headlamp-admin"
else
    log "ClusterRoleBinding already exists"
fi

#######################################
# Namespaces
#######################################

readonly NAMESPACE_DIR="k8s/namespaces"

log "Applying all namespaces"
for ns_file in "$NAMESPACE_DIR"/*.yaml; do
    if [[ -f "$ns_file" ]]; then
        kubectl apply -f "$ns_file"
    else
        warn "Namespace file not found: $ns_file"
    fi
done

#######################################
# CRDs
#######################################

readonly CRD_DIR="k8s/crds"

log "Applying all CRDs"
for crd_file in "$CRD_DIR"/*.yaml; do
    if [[ -f "$crd_file" ]]; then
        kubectl apply -f "$crd_file"
    else
        warn "CRD file not found: $crd_file"
    fi
done

#######################################
# Gatekeeper
#######################################

readonly GATEKEEPER_VERSION="v3.22.2"
readonly GATEKEEPER_NAMESPACE="gatekeeper-system"
readonly GATEKEEPER_MANIFEST_URL="https://raw.githubusercontent.com/open-policy-agent/gatekeeper/${GATEKEEPER_VERSION}/deploy/gatekeeper.yaml"

readonly GATEKEEPER_CONFIG_FILE="k8s/gatekeeper-config.yaml"

readonly TEMPLATE_CONSTRAINT_DIRS=(
    "k8s/policy/validate-task-request-datasets-error"
    "k8s/policy/validate-task-request-datasets-properties"
    "k8s/policy/validate-task-request-namespace"
    "k8s/policy/validate-task-request-properties"
)

log "Installing Gatekeeper"
kubectl apply -f "$GATEKEEPER_MANIFEST_URL"

log "Waiting for Gatekeeper to be ready..."
kubectl wait --for=condition=Available deployment/gatekeeper-controller-manager -n "$GATEKEEPER_NAMESPACE" --timeout=120s
kubectl wait --for=condition=Available deployment/gatekeeper-audit -n "$GATEKEEPER_NAMESPACE" --timeout=120s

log "Applying Gatekeeper configuration"
for attempt in {1..10}; do
    if kubectl apply -f "$GATEKEEPER_CONFIG_FILE"; then
        break
    fi

    if [[ $attempt -eq 10 ]]; then
        error "Unable to apply Gatekeeper configuration after retries"
        exit 1
    fi

    warn "Gatekeeper webhook not ready, retrying ($attempt/10)..."
    sleep 3
done

log "Applying ConstraintTemplates..."
for template_dir in "${TEMPLATE_CONSTRAINT_DIRS[@]}"; do
    template_file="$template_dir/template.yaml"

    if [[ -f "$template_file" ]]; then
        kubectl apply -f "$template_file"
    else
        warn "ConstraintTemplate file not found: $template_file"
    fi
done

log "Waiting for all Gatekeeper Constraint CRDs to be established..."
kubectl wait --for=condition=Established crd -l gatekeeper.sh/constraint=yes --timeout=120s

log "Applying Constraints..."
for constraint_dir in "${TEMPLATE_CONSTRAINT_DIRS[@]}"; do
    constraint_file="$constraint_dir/constraint.yaml"

    if [[ -f "$constraint_file" ]]; then
        kubectl apply -f "$constraint_file"
    else
        warn "Constraint file not found: $constraint_file"
    fi
done

#######################################
# Node-property-controller 
#######################################

readonly NODE_PROPERTY_CONTROLLER_PATH="node-property-controller"
readonly NODE_PROPERTY_CONTROLLER_IMAGE="node-property-controller:latest"
readonly NODE_PROPERTY_CONTROLLER_FILES=(
    "node-property-controller/k8s/namespace.yaml"
    "node-property-controller/k8s/network-policy.yaml"
    "node-property-controller/k8s/rbac.yaml"
    "node-property-controller/k8s/deployment.yaml"
)
readonly NODE_PROPERTY_CONTROLLER_NAMESPACE="node-property-controller"
readonly NODE_PROPERTY_CONTROLLER_DEPLOYMENT="node-property-controller"

log "Setting up node-property-controller"
if command_exist docker; then
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

log "Deploying node-property-controller"
for node_property_file in "${NODE_PROPERTY_CONTROLLER_FILES[@]}"; do
    if [[ -f "$node_property_file" ]]; then
        kubectl apply -f "$node_property_file"
    else
        warn "File not found: $node_property_file"
    fi
done

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
# Summary
#######################################

log "Cluster information"

kubectl get nodes -o wide

log "k8s-init: completed successfully!"
