#!/usr/bin/env bash
#
# Applies namespace manifests and the project's CRDs.
# Prerequisite: existing kind cluster with an active kubectl context.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"

step_namespaces_crds() {
    local namespace_dir="k8s/namespaces"
    local crd_dir="k8s/crds"

    log "Applying namespaces"
    kubectl apply -f "$namespace_dir/"

    log "Applying CRDs"
    kubectl apply -f "$crd_dir/"
}

# Run the step if this script is executed directly, not sourced
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    setup_error_trap
    require_command kubectl
    step_namespaces_crds
    log "Namespaces/CRDs step completed"
fi
