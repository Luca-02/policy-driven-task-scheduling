#!/usr/bin/env bash
#
# Builds, loads and deploys the scheduler.
# Prerequisite: dataset-service and context-service already deployed, with
# their respective TLS secrets present in their namespaces.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"

step_scheduler() {
    local scheduler_path="scheduler"
    local scheduler_image="scheduler:latest"

    log "Setting up scheduler image"
    load_image "$scheduler_path" "$scheduler_image"

    local scheduler_namespace="scheduler"
    local scheduler_deployment="scheduler"

    local dataset_service_namespace="dataset-service"
    local dataset_service_tls_secret="dataset-service-tls"
    local context_service_namespace="context-service"
    local context_service_tls_secret="context-service-tls"

    copy_ca_secret "$dataset_service_namespace" "$scheduler_namespace" "$dataset_service_tls_secret"
    copy_ca_secret "$context_service_namespace" "$scheduler_namespace" "$context_service_tls_secret"

    log "Creating scheduler-config ConfigMap"
    kubectl create configmap scheduler-config \
        --from-file=scheduler-config.yaml="${scheduler_path}/k8s/scheduler-config.yaml" \
        -n "$scheduler_namespace" \
        --dry-run=client -o yaml | kubectl apply -f -

    log "Applying scheduler manifests"
    kubectl apply -f "${scheduler_path}/k8s/rbac.yaml"
    kubectl apply -f "${scheduler_path}/k8s/deployment.yaml"
    kubectl apply -f "${scheduler_path}/k8s/network-policy.yaml"

    wait_for_deployment "$scheduler_namespace" "$scheduler_deployment"
}

# Run the step if this script is executed directly, not sourced
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    setup_error_trap
    require_command kubectl
    step_scheduler
    log "scheduler step completed"
fi
