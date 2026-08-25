#!/usr/bin/env bash
#
# Installs Gatekeeper and applies the project's ConstraintTemplates/Constraints.
# Prerequisite: namespaces/CRDs applied, if the Constraints reference the 
# project's custom CRDs.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"

step_gatekeeper() {
    local gatekeeper_version="v3.22.2"
    local gatekeeper_namespace="gatekeeper-system"
    local gatekeeper_manifest_url="https://raw.githubusercontent.com/open-policy-agent/gatekeeper/${gatekeeper_version}/deploy/gatekeeper.yaml"

    local gatekeeper_config_file="k8s/gatekeeper-config.yaml"

    local template_constraint_dirs=(
        "k8s/policies/validate-task-request-namespace"
        "k8s/policies/validate-task-request-properties"
        "k8s/policies/validate-task-request-geographical-group"
        "k8s/policies/validate-task-request-datasets"
    )

    log "Installing Gatekeeper"
    kubectl apply -f "$gatekeeper_manifest_url"

    local gatekeeper_cache_ttl="1m"

    log "Patching Gatekeeper with external-data-provider-response-cache-ttl"
    kubectl patch deployment gatekeeper-controller-manager \
        -n "$gatekeeper_namespace" \
        --type=json \
        -p="[
        {
            \"op\": \"add\",
            \"path\": \"/spec/template/spec/containers/0/args/-\",
            \"value\": \"--enable-external-data=true\"
        },
        {
            \"op\": \"add\",
            \"path\": \"/spec/template/spec/containers/0/args/-\",
            \"value\": \"--external-data-provider-response-cache-ttl=${gatekeeper_cache_ttl}\"
        }
    ]"

    wait_for_deployment "$gatekeeper_namespace" "gatekeeper-controller-manager"
    wait_for_deployment "$gatekeeper_namespace" "gatekeeper-audit"

    log "Applying Gatekeeper configuration"
    apply_with_retry "$gatekeeper_config_file" "Gatekeeper configuration" "$MAX_RETRIES"

    log "Applying ConstraintTemplates"
    local template_dir template_file
    for template_dir in "${template_constraint_dirs[@]}"; do
        template_file="$template_dir/template.yaml"
        if [[ -f "$template_file" ]]; then
            kubectl apply -f "$template_file"
        fi
    done

    log "Waiting for all Gatekeeper Constraint CRDs to be established"
    kubectl wait --for=condition=Established crd -l gatekeeper.sh/constraint=yes --timeout=300s

    log "Applying Constraints"
    local constraint_dir constraint_file
    for constraint_dir in "${template_constraint_dirs[@]}"; do
        constraint_file="$constraint_dir/constraint.yaml"
        if [[ -f "$constraint_file" ]]; then
            kubectl apply -f "$constraint_file"
        fi
    done
}

# Run the step if this script is executed directly, not sourced
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    setup_error_trap
    require_command kubectl
    step_gatekeeper
    log "Gatekeeper step completed"
fi
