#!/usr/bin/env bash
#
# Installs Headlamp and creates the admin ServiceAccount/ClusterRoleBinding.
# Prerequisite: existing kind cluster with an active kubectl context.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"

step_headlamp() {
    local headlamp_manifest_url="https://raw.githubusercontent.com/kinvolk/headlamp/main/kubernetes-headlamp.yaml"

    log "Installing Headlamp"
    kubectl apply -f "$headlamp_manifest_url"

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

    log "To access Headlamp, retrieve the token with: kubectl create token headlamp-admin -n kube-system"
    log "The port-forward with: kubectl port-forward -n kube-system svc/headlamp 8080:80"
}

# Run the step if this script is executed directly, not sourced
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    setup_error_trap
    require_command kubectl
    step_headlamp
    log "Headlamp step completed"
fi
