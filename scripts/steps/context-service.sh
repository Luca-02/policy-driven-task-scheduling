#!/usr/bin/env bash
#
# Deploys context-service: CloudNativePG Cluster (unless light mode), TLS,
# image and manifests.
# Prerequisite: CloudNativePG operator installed if not in light mode, 
# existing kind cluster with an active kubectl context.
#
# Optional variables:
#   CONTEXT_SERVICE_LIGHT_MODE (default: false)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"

step_context_service() {
    local context_service_path="context-service"
    local context_service_light_mode="${CONTEXT_SERVICE_LIGHT_MODE:-false}"

    if [[ "$context_service_light_mode" == "true" ]]; then
        log "Context service light mode enabled, skipping postgres cluster setup"
    else
        log "Applying CloudNativePG postgres cluster manifest"
        apply_with_retry "$context_service_path/k8s/postgres-cluster.yaml" "CloudNativePG" "$MAX_RETRIES"

        log "Waiting for CloudNativePG postgres cluster to be ready"
        kubectl wait -n context-service \
            --for=condition=Ready cluster/context-db \
            --timeout=600s
    fi

    local context_service="context-service"
    local context_service_namespace="context-service"
    local context_service_deployment="context-service"
    local context_service_tls_secret="context-service-tls"

    setup_service_tls "$context_service_path" "$context_service" "$context_service_namespace" "$context_service_tls_secret"

    local context_service_image="context-service:latest"

    log "Setting up context-service image"
    load_image "$context_service_path" "$context_service_image"

    log "Applying context-service manifests"
    kubectl apply -f "${context_service_path}/k8s/service.yaml"
    if [[ "$context_service_light_mode" == "true" ]]; then
        kubectl apply -f "${context_service_path}/k8s/deployment-light.yaml"
    else
        kubectl apply -f "${context_service_path}/k8s/deployment.yaml"
    fi
    kubectl apply -f "${context_service_path}/k8s/network-policy.yaml"

    wait_for_deployment "$context_service_namespace" "$context_service_deployment"
}

# Run the step if this script is executed directly, not sourced
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    setup_error_trap
    require_command kubectl
    step_context_service
    log "context-service step completed"
fi
