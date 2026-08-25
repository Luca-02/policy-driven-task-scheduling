#!/usr/bin/env bash
#
# Functions and variables shared by init-cluster.sh and all steps in
# scripts/steps/. This file must always be sourced, never executed directly.
#
# NB: it assumes it's invoked with the working directory set to the repository 
# root (ROOT_DIR = pwd at source time).

# Guard against double-sourcing: init-cluster.sh sources all steps in
# sequence, and each of them sources this file in turn. Without this guard,
# the second "readonly" on the same variables would make the script fail.
if [[ -n "${__COMMON_SH_INCLUDED:-}" ]]; then
    return 0
fi
readonly __COMMON_SH_INCLUDED=1

set -euo pipefail

readonly CLUSTER_NAME="${CLUSTER_NAME:-kind}"
readonly MAX_RETRIES="${MAX_RETRIES:-10}"

# Captured at source time, so shared scripts (e.g. scripts/gen-certs.sh) are
# always referenceable by absolute path regardless of where in the repo the
# current action happens to run (e.g. inside setup_service_tls, which cd's
# into a service subdirectory).
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
# Error trap
#######################################

setup_error_trap() {
    trap '_on_exit $?' EXIT
}

_on_exit() {
    local exit_code=$1
    if [[ $exit_code -ne 0 ]]; then
        error "Script failed with exit code $exit_code"
    fi
}

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

apply_with_retry() {
    local file="$1"
    local label="$2"
    local max_retries="${3:-$MAX_RETRIES}"

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
    local timeout="${3:-300s}" # default timeout of 300 seconds

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

setup_service_tls() {
    local path="$1"
    local svc="$2"
    local ns="$3"
    local secret="$4"
    local target_env="${5:-k8s}"
    local certs_dir="${6:-.certs}"

    log "Generating TLS certificates for $svc"
    (
        cd "$path"

        log "Creating TLS secret for $svc"
        if kubectl get secret "$secret" -n "$ns" >/dev/null 2>&1; then
            log "TLS secret for $svc already exists"
        else
            TARGET_ENV=$target_env SVC=$svc NS=$ns \
                bash "$ROOT_DIR/scripts/gen-certs.sh" "$certs_dir"

            kubectl create secret generic "$secret" \
                --from-file=ca.crt="$certs_dir/${target_env}/ca.crt" \
                --from-file=tls.crt="$certs_dir/${target_env}/tls.crt" \
                --from-file=tls.key="$certs_dir/${target_env}/tls.key" \
                -n "$ns" \
                --dry-run=client -o yaml | kubectl apply -f -
        fi

        log "Rendering and applying $svc provider (caBundle injected at apply time)"
        CA_B64=$(kubectl get secret "$secret" -n "$ns" -o jsonpath='{.data.ca\.crt}')
        sed "s|<CA_BUNDLE>|${CA_B64}|" "k8s/provider.yaml" | kubectl apply -f -
    )
}
