#!/usr/bin/env bash
#
# Installs the CloudNativePG operator (controller only, not the individual
# postgres Clusters, which are created by the dataset-service and
# context-service steps). Skipped if both services run in light mode.
# Prerequisite: existing kind cluster with an active kubectl context.
#
# Optional variables:
#   DATASET_SERVICE_LIGHT_MODE / CONTEXT_SERVICE_LIGHT_MODE (default: false)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"

step_cloudnative_pg() {
    local cloudnative_pg_namespace="cnpg-system"
    local cloudnative_pg_manifest_url="https://raw.githubusercontent.com/cloudnative-pg/cloudnative-pg/release-1.30/releases/cnpg-1.30.0.yaml"

    log "Installing CloudNativePG"
    kubectl apply --server-side -f "$cloudnative_pg_manifest_url"

    wait_for_deployment "$cloudnative_pg_namespace" "cnpg-controller-manager"

    kubectl wait -n "$cloudnative_pg_namespace" \
        --for=condition=ready pod -l app.kubernetes.io/name=cloudnative-pg \
        --timeout=600s

    log "Waiting for CloudNativePG CRDs to be established"
    kubectl wait --for=condition=Established crd/clusters.postgresql.cnpg.io --timeout=600s
}

# Run the step if this script is executed directly, not sourced
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    setup_error_trap
    require_command kubectl
    step_cloudnative_pg
    log "CloudNativePG step completed"
fi
