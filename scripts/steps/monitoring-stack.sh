#!/usr/bin/env bash
#
# Installs kube-prometheus-stack + Loki via Helm.
# Prerequisite: existing kind cluster with an active kubectl context.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"

step_monitoring_stack() {
    local namespace="monitoring"
    local prom_release="kube-prometheus-stack"
    local loki_release="loki"

    log "Setting up Kube-Prometheus-Stack + Loki via Helm"

    log "Creating namespace '$namespace' (if not exists)"
    kubectl create namespace "$namespace" --dry-run=client -o yaml | kubectl apply -f -

    log "Adding and updating Helm repositories"
    helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
    helm repo add grafana https://grafana.github.io/helm-charts
    helm repo update

    log "Installing Kube-Prometheus-Stack with automatic Loki Data Source provisioning"

    # Install kube-prometheus-stack with the temporary values file
    helm upgrade --install "$prom_release" prometheus-community/kube-prometheus-stack \
        --namespace "$namespace"

    log "Installing Loki Stack (Promtail, Loki)"
    # Install Loki stack with Promtail enabled and Grafana disabled avoiding duplicate Grafana installations
    # Set loki.isDefault to false to avoid conflicts with the default Loki instance created by kube-prometheus-stack
    helm upgrade --install "$loki_release" grafana/loki-stack \
        --namespace "$namespace" \
        --set grafana.enabled=false \
        --set promtail.enabled=true \
        --set loki.isDefault=false

    log "To access Grafana, retrieve the admin password with: \n
        kubectl get secret --namespace $namespace ${prom_release}-grafana -o jsonpath=\"{.data.admin-password}\" | base64 --decode"
    
    log "Then port-forward with: \n 
        kubectl port-forward -n $namespace svc/${prom_release}-grafana 3000:80"
}

# Run the step if this script is executed directly, not sourced
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    setup_error_trap
    require_command kubectl
    require_command helm
    step_observability_stack
    log "Observability stack step completed"
fi
