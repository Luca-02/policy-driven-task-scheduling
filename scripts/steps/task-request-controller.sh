#!/usr/bin/env bash
#
# Builds, loads and deploys task-request-controller.
# Prerequisite: dataset-service already deployed, with the TLS secret
# "dataset-service-tls" present in its namespace.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"

step_task_request_controller() {
    local task_request_controller_path="task-request-controller"
    local task_request_controller_image="task-request-controller:latest"

    log "Setting up task-request-controller image"
    load_image "$task_request_controller_path" "$task_request_controller_image"

    local task_request_controller_namespace="task-request-controller"
    local task_request_controller_deployment="task-request-controller"

    local dataset_service_namespace="dataset-service"
    local dataset_service_tls_secret="dataset-service-tls"

    copy_ca_secret "$dataset_service_namespace" "$task_request_controller_namespace" "$dataset_service_tls_secret"

    log "Applying task-request-controller manifests"
    kubectl apply -f "${task_request_controller_path}/k8s/rbac.yaml"
    kubectl apply -f "${task_request_controller_path}/k8s/deployment.yaml"
    kubectl apply -f "${task_request_controller_path}/k8s/network-policy.yaml"

    wait_for_deployment "$task_request_controller_namespace" "$task_request_controller_deployment"
}

# Run the step if this script is executed directly, not sourced
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    setup_error_trap
    require_command kubectl
    step_task_request_controller
    log "task-request-controller step completed"
fi
