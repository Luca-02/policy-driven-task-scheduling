#!/usr/bin/env bash
#
# Builds (if docker is available), loads and deploys node-controller.
# Prerequisite: existing kind cluster with an active kubectl context.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"

step_node_controller() {
    local node_controller_path="node-controller"
    local node_controller_image="node-controller:latest"

    log "Setting up node-controller image"
    load_image "$node_controller_path" "$node_controller_image"

    local node_controller_namespace="node-controller"
    local node_controller_deployment="node-controller"

    log "Applying node-controller manifests"
    kubectl apply -f "${node_controller_path}/k8s/rbac.yaml"
    kubectl apply -f "${node_controller_path}/k8s/deployment.yaml"
    kubectl apply -f "${node_controller_path}/k8s/network-policy.yaml"

    wait_for_deployment "$node_controller_namespace" "$node_controller_deployment"
}

# Run the step if this script is executed directly, not sourced
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    setup_error_trap
    require_command kubectl
    step_node_controller
    log "node-controller step completed"
fi
