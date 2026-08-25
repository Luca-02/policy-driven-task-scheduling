#!/usr/bin/env bash
#
# Deploys dataset-service: CloudNativePG Cluster (unless light mode), TLS,
# image and manifests.
# Prerequisite: CloudNativePG operator installed if not in light mode, 
# existing kind cluster with an active kubectl context.
#
# Optional variables:
#   DATASET_SERVICE_LIGHT_MODE (default: false)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"

step_dataset_service() {
    local dataset_service_path="dataset-service"
    local dataset_service_light_mode="${DATASET_SERVICE_LIGHT_MODE:-false}"

    if [[ "$dataset_service_light_mode" == "true" ]]; then
        log "Dataset service light mode enabled, skipping postgres cluster setup"
    else
        log "Applying CloudNativePG postgres cluster manifest"
        apply_with_retry "$dataset_service_path/k8s/postgres-cluster.yaml" "CloudNativePG" "$MAX_RETRIES"

        log "Waiting for CloudNativePG postgres cluster to be ready"
        kubectl wait -n dataset-service \
            --for=condition=Ready cluster/dataset-db \
            --timeout=600s
    fi

    local dataset_service="dataset-service"
    local dataset_service_namespace="dataset-service"
    local dataset_service_deployment="dataset-service"
    local dataset_service_tls_secret="dataset-service-tls"

    setup_service_tls "$dataset_service_path" "$dataset_service" "$dataset_service_namespace" "$dataset_service_tls_secret"

    local dataset_service_image="dataset-service:latest"

    log "Setting up dataset-service image"
    load_image "$dataset_service_path" "$dataset_service_image"

    log "Applying dataset-service manifests"
    kubectl apply -f "${dataset_service_path}/k8s/service.yaml"
    if [[ "$dataset_service_light_mode" == "true" ]]; then
        kubectl apply -f "${dataset_service_path}/k8s/deployment-light.yaml"
    else
        kubectl apply -f "${dataset_service_path}/k8s/deployment.yaml"
    fi
    kubectl apply -f "${dataset_service_path}/k8s/network-policy.yaml"

    wait_for_deployment "$dataset_service_namespace" "$dataset_service_deployment"
}

# Run the step if this script is executed directly, not sourced
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    setup_error_trap
    require_command kubectl
    step_dataset_service
    log "dataset-service step completed"
fi
