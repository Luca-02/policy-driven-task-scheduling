#!/usr/bin/env bash

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
# Cleanup on exit
#######################################

cleanup() {
    local exit_code=$?

    if [[ $exit_code -ne 0 ]]; then
        error "Script failed with exit code $exit_code"
    else
        log "Cluster nodes information:"
        kubectl get nodes -o wide

        log "Cluster initialized successfully!"
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

load_image() {
    local path="$1"
    local image="$2"

    if command_exist docker; then
        if docker image inspect "$image" >/dev/null 2>&1; then
            log "Docker image '$image' already exists"
        else
            log "Docker image '$image' not found, building from $path/"

            if [[ ! -f "$path/Dockerfile" ]]; then
                error "Dockerfile not found in $path/"
                exit 1
            fi

            docker build -t "$image" "$path/"
        fi

        log "Loading image '$image' into cluster '$CLUSTER_NAME'"
        kind load docker-image "$image" --name "$CLUSTER_NAME"
    else
        warn "Docker not available, skipping build and load"
    fi
}

wait_for_deployment() {
    local ns="$1"
    local deploy="$2"
    local timeout="${3:-180s}" # default timeout of 180 seconds

    log "Waiting for deployment '$deploy' in namespace '$ns'"
    if ! kubectl -n "$ns" rollout status deployment/"$deploy" --timeout="$timeout"; then
        warn "Deployment '$deploy' did not become ready within timeout"
        
        log "Dumping pod status for debugging:"
        kubectl -n "$ns" get pods -l app.kubernetes.io/name="$deploy" -o wide || true
        
        log "Recent logs:"
        kubectl -n "$ns" logs deployment/"$deploy" --tail=100 || true
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
    kind create cluster --name "$CLUSTER_NAME" --config "$CLUSTER_CONFIG_FILE"
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
kubectl apply -f "$HEADLAMP_MANIFEST_URL"

log "Ensuring Headlamp admin service account"
if ! resource_exists -n kube-system get serviceaccount headlamp-admin; then
    log "Creating ServiceAccount kube-system/headlamp-admin"
    kubectl -n kube-system create serviceaccount headlamp-admin
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
# Namespaces and CRDs
#######################################

readonly NAMESPACE_DIR="k8s/namespaces"
readonly CRD_DIR="k8s/crds"

log "Applying namespaces"
kubectl apply -f "$NAMESPACE_DIR/"

log "Applying CRDs"
kubectl apply -f "$CRD_DIR/"

#######################################
# Gatekeeper
#######################################

readonly GATEKEEPER_VERSION="v3.22.2"
readonly GATEKEEPER_NAMESPACE="gatekeeper-system"
readonly GATEKEEPER_MANIFEST_URL="https://raw.githubusercontent.com/open-policy-agent/gatekeeper/${GATEKEEPER_VERSION}/deploy/gatekeeper.yaml"

readonly GATEKEEPER_CONFIG_FILE="k8s/gatekeeper-config.yaml"

readonly TEMPLATE_CONSTRAINT_DIRS=(
    "k8s/policies/validate-task-request-namespace"
    "k8s/policies/validate-task-request-properties"
    "k8s/policies/validate-task-request-datasets"
)

log "Installing Gatekeeper"
kubectl apply -f "$GATEKEEPER_MANIFEST_URL"

wait_for_deployment "$GATEKEEPER_NAMESPACE" "gatekeeper-controller-manager"
wait_for_deployment "$GATEKEEPER_NAMESPACE" "gatekeeper-audit"

log "Applying Gatekeeper configuration"
readonly MAX_RETRIES=10
for attempt in {1..$MAX_RETRIES}; do
    if kubectl apply -f "$GATEKEEPER_CONFIG_FILE"; then
        break
    fi

    if [[ $attempt -eq $MAX_RETRIES ]]; then
        error "Unable to apply Gatekeeper configuration after retries"
        exit 1
    fi

    warn "Gatekeeper webhook not ready, retrying ($attempt/$MAX_RETRIES)..."
    sleep 3
done

log "Applying ConstraintTemplates"
for template_dir in "${TEMPLATE_CONSTRAINT_DIRS[@]}"; do
    template_file="$template_dir/template.yaml"
    if [[ -f "$template_file" ]]; then
        kubectl apply -f "$template_file"
    fi
done

log "Waiting for all Gatekeeper Constraint CRDs to be established"
kubectl wait --for=condition=Established crd -l gatekeeper.sh/constraint=yes --timeout=120s

log "Applying Constraints"
for constraint_dir in "${TEMPLATE_CONSTRAINT_DIRS[@]}"; do
    constraint_file="$constraint_dir/constraint.yaml"
    if [[ -f "$constraint_file" ]]; then
        kubectl apply -f "$constraint_file"
    fi
done

#######################################
# node-property-controller 
#######################################

readonly NODE_PROPERTY_CONTROLLER_PATH="node-property-controller"
readonly NODE_PROPERTY_CONTROLLER_IMAGE="node-property-controller:latest"

log "Setting up node-property-controller image"
load_image "$NODE_PROPERTY_CONTROLLER_PATH" "$NODE_PROPERTY_CONTROLLER_IMAGE"

readonly NODE_PROPERTY_CONTROLLER_NAMESPACE="node-property-controller"
readonly NODE_PROPERTY_CONTROLLER_DEPLOYMENT="node-property-controller"

log "Applying node-property-controller manifests"
kubectl apply -f "${NODE_PROPERTY_CONTROLLER_PATH}/k8s/rbac.yaml"
kubectl apply -f "${NODE_PROPERTY_CONTROLLER_PATH}/k8s/network-policy.yaml"
kubectl apply -f "${NODE_PROPERTY_CONTROLLER_PATH}/k8s/deployment.yaml"

wait_for_deployment "$NODE_PROPERTY_CONTROLLER_NAMESPACE" "$NODE_PROPERTY_CONTROLLER_DEPLOYMENT"

#######################################
# dataset-service
#######################################

readonly CLOUDNATIVE_PG_RELEASE="release-1.29" 
readonly CLOUDNATIVE_PG_MANIFEST="cnpg-1.29.1"
readonly CLOUDNATIVE_PG_NAMESPACE="cnpg-system"
readonly CLOUDNATIVE_PG_MANIFEST_URL="https://raw.githubusercontent.com/cloudnative-pg/cloudnative-pg/${CLOUDNATIVE_PG_RELEASE}/releases/${CLOUDNATIVE_PG_MANIFEST}.yaml"

log "Installing CloudNativePG"
kubectl apply --server-side -f "$CLOUDNATIVE_PG_MANIFEST_URL"

wait_for_deployment "$CLOUDNATIVE_PG_NAMESPACE" "cnpg-controller-manager"
kubectl wait -n "$CLOUDNATIVE_PG_NAMESPACE" \
    --for=condition=ready pod -l app.kubernetes.io/name=cloudnative-pg \
    --timeout=120s

log "Waiting for CloudNativePG CRDs to be established"
kubectl wait --for=condition=Established crd/clusters.postgresql.cnpg.io --timeout=120s

readonly DATASET_SERVICE_PATH="dataset-service"
readonly DATASET_SERVICE_IMAGE="dataset-service:latest"

log "Applying CloudNativePG postgres cluster manifest"
kubectl apply -f "$DATASET_SERVICE_PATH/k8s/postgres-cluster.yaml"

log "Waiting for CloudNativePG postgres cluster to be ready"
kubectl wait -n dataset-service \
    --for=condition=Ready cluster/dataset-db \
    --timeout=600s

readonly DATASET_SERVICE="dataset-service"
readonly DATASET_SERVICE_NAMESPACE="dataset-service"
readonly DATASET_SERVICE_DEPLOYMENT="dataset-service"

log "Generating TLS certificates for dataset-service"
(
    cd "$DATASET_SERVICE_PATH"

    readonly CERTS_DIR=".certs"

    TARGET_ENV="k8s" SVC=$DATASET_SERVICE NS=$DATASET_SERVICE_NAMESPACE \
        bash scripts/gen-certs.sh "$CERTS_DIR"

    log "Creating dataset-service-tls secret in Kubernetes"
    kubectl create secret generic dataset-service-tls \
        --from-file=ca.crt="$CERTS_DIR/k8s/ca.crt" \
        --from-file=tls.crt="$CERTS_DIR/k8s/tls.crt" \
        --from-file=tls.key="$CERTS_DIR/k8s/tls.key" \
        -n "$DATASET_SERVICE_NAMESPACE" \
        --dry-run=client -o yaml | kubectl apply -f -
)

log "Setting up dataset-service image"
load_image "$DATASET_SERVICE_PATH" "$DATASET_SERVICE_IMAGE"

log "Applying dataset-service manifests"
kubectl apply -f "${DATASET_SERVICE_PATH}/k8s/service.yaml"
kubectl apply -f "${DATASET_SERVICE_PATH}/k8s/network-policy.yaml"
kubectl apply -f "${DATASET_SERVICE_PATH}/k8s/deployment.yaml"

log "Applying dataset-service provider for gatekeeper external data"
kubectl apply -f "${DATASET_SERVICE_PATH}/k8s/provider.yaml"

wait_for_deployment "$DATASET_SERVICE_NAMESPACE" "$DATASET_SERVICE_DEPLOYMENT"
