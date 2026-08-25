#!/usr/bin/env bash
#
# Installs/upgrades the PLG stack (Promtail, Loki, Grafana) via Helm.
# Prerequisite: existing kind cluster with an active kubectl context.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"

step_plg_stack() {
    local loki_namespace="loki"
    local loki_stack_release="loki"

    log "Setting up PLG Stack via Helm"

    log "Creating namespace '$loki_namespace' (if not exists)"
    kubectl create namespace "$loki_namespace" --dry-run=client -o yaml | kubectl apply -f -

    log "Adding and updating Grafana Helm repository"
    helm repo add grafana https://grafana.github.io/helm-charts
    helm repo update

    log "Installing/Upgrading Loki Stack (Promtail, Loki, Grafana)"
    helm upgrade --install "$loki_stack_release" grafana/loki-stack \
        --namespace "$loki_namespace" \
        --set grafana.enabled=true \
        --set promtail.enabled=true

    log "To access Grafana, retrieve the admin password with: kubectl get secret --namespace $loki_namespace ${loki_stack_release}-grafana -o jsonpath=\"{.data.admin-password}\" | base64 --decode"
    log "The port-forward with: kubectl port-forward -n $loki_namespace svc/${loki_stack_release}-grafana 3000:80"
}

# Run the step if this script is executed directly, not sourced
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    setup_error_trap
    require_command kubectl
    require_command helm
    step_plg_stack
    log "PLG stack step completed"
fi
