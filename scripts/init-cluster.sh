#!/usr/bin/env bash

set -euo pipefail

readonly CLUSTER_NAME="${CLUSTER_NAME:-kind}"

# Captured before any subshell below cd's into a service directory, so that
# shared scripts (e.g. scripts/gen-certs.sh) can always be referenced by
# absolute path regardless of the caller's current directory.
readonly ROOT_DIR="$(pwd)"

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
        log "Building image '$image' from $path/"
        if [[ ! -f "$path/Dockerfile" ]]; then
            error "Dockerfile not found in $path/"
            exit 1
        fi
        docker build -t "$image" "$path/"

        log "Loading image '$image' into cluster '$CLUSTER_NAME'"
        kind load docker-image "$image" --name "$CLUSTER_NAME"
    else
        warn "Docker not available, skipping build and load"
    fi
}

readonly MAX_RETRIES=10

apply_with_retry() {
    local file="$1"
    local label="$2"
    local max_retries="${3:-10}"

    for attempt in $(seq 1 "$max_retries"); do
        if kubectl apply -f "$file"; then
            return 0
        fi

        if [[ $attempt -eq $max_retries ]]; then
            error "Unable to apply $label after $max_retries retries"
            exit 1
        fi

        warn "$label webhook not ready, retrying ($attempt/$max_retries)..."
        sleep 3
    done
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

copy_ca_secret() {
    local from_namespace="$1"
    local to_namespace="$2"
    local secret="$3"
    
    log "Extracting CA certificate from secret '$secret' in namespace '$from_namespace'"
    kubectl get secret "$secret" \
        -n "$from_namespace" \
        -o jsonpath='{.data.ca\.crt}' | base64 -d > /tmp/ca.crt

    log "Creating secret '$secret' in namespace '$to_namespace'"
    kubectl create secret generic "$secret" \
        --from-file=ca.crt=/tmp/ca.crt \
        -n "$to_namespace" \
        --dry-run=client -o yaml | kubectl apply -f -

    rm -f /tmp/ca.crt
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
    "k8s/policies/validate-task-request-geographical-group"
    "k8s/policies/validate-task-request-datasets"
)

log "Installing Gatekeeper"
kubectl apply -f "$GATEKEEPER_MANIFEST_URL"

readonly GATEKEEPER_CACHE_TTL="1m"

log "Patching Gatekeeper with external-data-provider-response-cache-ttl"
kubectl patch deployment gatekeeper-controller-manager \
  -n "$GATEKEEPER_NAMESPACE" \
  --type=json \
  -p="[
    {
        \"op\": \"add\",
        \"path\": \"/spec/template/spec/containers/0/args/-\",
        \"value\": \"--enable-external-data=true\"
    },
    {
        \"op\": \"add\",
        \"path\": \"/spec/template/spec/containers/0/args/-\",
        \"value\": \"--external-data-provider-response-cache-ttl=${GATEKEEPER_CACHE_TTL}\"
    }
  ]"

wait_for_deployment "$GATEKEEPER_NAMESPACE" "gatekeeper-controller-manager"
wait_for_deployment "$GATEKEEPER_NAMESPACE" "gatekeeper-audit"

log "Applying Gatekeeper configuration"
apply_with_retry "$GATEKEEPER_CONFIG_FILE" "Gatekeeper configuration" "$MAX_RETRIES"

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
# CloudNativePG
#######################################

readonly CLOUDNATIVE_PG_NAMESPACE="cnpg-system"
readonly CLOUDNATIVE_PG_MANIFEST_URL="https://raw.githubusercontent.com/cloudnative-pg/cloudnative-pg/release-1.30/releases/cnpg-1.30.0.yaml"

log "Installing CloudNativePG"
kubectl apply --server-side -f "$CLOUDNATIVE_PG_MANIFEST_URL"

wait_for_deployment "$CLOUDNATIVE_PG_NAMESPACE" "cnpg-controller-manager"
kubectl wait -n "$CLOUDNATIVE_PG_NAMESPACE" \
    --for=condition=ready pod -l app.kubernetes.io/name=cloudnative-pg \
    --timeout=120s

log "Waiting for CloudNativePG CRDs to be established"
kubectl wait --for=condition=Established crd/clusters.postgresql.cnpg.io --timeout=120s

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

readonly DATASET_SERVICE_PATH="dataset-service"
readonly DATASET_SERVICE_LIGHT_MODE="${DATASET_SERVICE_LIGHT_MODE:-false}"

if [[ "$DATASET_SERVICE_LIGHT_MODE" == "true" ]]; then
    log "Dataset service light mode enabled, skipping postgres cluster setup"
else
    log "Applying CloudNativePG postgres cluster manifest"
    apply_with_retry "$DATASET_SERVICE_PATH/k8s/postgres-cluster.yaml" "CloudNativePG" "$MAX_RETRIES"

    log "Waiting for CloudNativePG postgres cluster to be ready"
    kubectl wait -n dataset-service \
        --for=condition=Ready cluster/dataset-db \
        --timeout=600s
fi

readonly DATASET_SERVICE="dataset-service"
readonly DATASET_SERVICE_NAMESPACE="dataset-service"
readonly DATASET_SERVICE_DEPLOYMENT="dataset-service"
readonly DATASET_SERVICE_TLS_SECRET="dataset-service-tls"

TARGET_ENV="k8s"
CERTS_DIR=".certs"

log "Generating TLS certificates for dataset-service"
(
    cd "$DATASET_SERVICE_PATH"

    log "Creating TLS secret for dataset-service"
    if kubectl get secret "$DATASET_SERVICE_TLS_SECRET" -n "$DATASET_SERVICE_NAMESPACE" >/dev/null 2>&1; then
        log "TLS secret for dataset-service already exists"
    else
        TARGET_ENV=$TARGET_ENV SVC=$DATASET_SERVICE NS=$DATASET_SERVICE_NAMESPACE \
            bash "$ROOT_DIR/scripts/gen-certs.sh" "$CERTS_DIR"

        kubectl create secret generic "$DATASET_SERVICE_TLS_SECRET" \
            --from-file=ca.crt="$CERTS_DIR/${TARGET_ENV}/ca.crt" \
            --from-file=tls.crt="$CERTS_DIR/${TARGET_ENV}/tls.crt" \
            --from-file=tls.key="$CERTS_DIR/${TARGET_ENV}/tls.key" \
            -n "$DATASET_SERVICE_NAMESPACE" \
            --dry-run=client -o yaml | kubectl apply -f -
    fi

    log "Rendering and applying dataset-service provider (caBundle injected at apply time)"
    CA_B64=$(kubectl get secret "$DATASET_SERVICE_TLS_SECRET" -n "$DATASET_SERVICE_NAMESPACE" -o jsonpath='{.data.ca\.crt}')
    sed "s|<CA_BUNDLE>|${CA_B64}|" "k8s/provider.yaml" | kubectl apply -f -
)

readonly DATASET_SERVICE_IMAGE="dataset-service:latest"

log "Setting up dataset-service image"
load_image "$DATASET_SERVICE_PATH" "$DATASET_SERVICE_IMAGE"

log "Applying dataset-service manifests"
kubectl apply -f "${DATASET_SERVICE_PATH}/k8s/service.yaml"
kubectl apply -f "${DATASET_SERVICE_PATH}/k8s/network-policy.yaml"
if [[ "$DATASET_SERVICE_LIGHT_MODE" == "true" ]]; then
    kubectl apply -f "${DATASET_SERVICE_PATH}/k8s/deployment-light.yaml"
else
    kubectl apply -f "${DATASET_SERVICE_PATH}/k8s/deployment.yaml"
fi

wait_for_deployment "$DATASET_SERVICE_NAMESPACE" "$DATASET_SERVICE_DEPLOYMENT"

#######################################
# task-request-controller
#######################################

readonly TASK_REQUEST_CONTROLLER_PATH="task-request-controller"
readonly TASK_REQUEST_CONTROLLER_IMAGE="task-request-controller:latest"

log "Setting up task-request-controller image"
load_image "$TASK_REQUEST_CONTROLLER_PATH" "$TASK_REQUEST_CONTROLLER_IMAGE"

readonly TASK_REQUEST_CONTROLLER_NAMESPACE="task-request-controller"
readonly TASK_REQUEST_CONTROLLER_DEPLOYMENT="task-request-controller"

copy_ca_secret "$DATASET_SERVICE_NAMESPACE" "$TASK_REQUEST_CONTROLLER_NAMESPACE" "$DATASET_SERVICE_TLS_SECRET"

log "Applying task-request-controller manifests"
kubectl apply -f "${TASK_REQUEST_CONTROLLER_PATH}/k8s/rbac.yaml"
kubectl apply -f "${TASK_REQUEST_CONTROLLER_PATH}/k8s/network-policy.yaml"
kubectl apply -f "${TASK_REQUEST_CONTROLLER_PATH}/k8s/deployment.yaml"

wait_for_deployment "$TASK_REQUEST_CONTROLLER_NAMESPACE" "$TASK_REQUEST_CONTROLLER_DEPLOYMENT"

#######################################
# scheduler
#######################################

readonly SCHEDULER_PATH="scheduler"
readonly SCHEDULER_IMAGE="scheduler:latest"

log "Setting up scheduler image"
load_image "$SCHEDULER_PATH" "$SCHEDULER_IMAGE"

readonly SCHEDULER_NAMESPACE="scheduler"
readonly SCHEDULER_DEPLOYMENT="scheduler"

copy_ca_secret "$DATASET_SERVICE_NAMESPACE" "$SCHEDULER_NAMESPACE" "$DATASET_SERVICE_TLS_SECRET"

log "Creating scheduler-config ConfigMap"
kubectl create configmap scheduler-config \
  --from-file=scheduler-config.yaml="${SCHEDULER_PATH}/k8s/scheduler-config.yaml" \
  -n "$SCHEDULER_NAMESPACE" \
  --dry-run=client -o yaml | kubectl apply -f -

log "Applying scheduler manifests"
kubectl apply -f "${SCHEDULER_PATH}/k8s/rbac.yaml"
kubectl apply -f "${SCHEDULER_PATH}/k8s/network-policy.yaml"
kubectl apply -f "${SCHEDULER_PATH}/k8s/deployment.yaml"

wait_for_deployment "$SCHEDULER_NAMESPACE" "$SCHEDULER_DEPLOYMENT"