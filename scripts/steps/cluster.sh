#!/usr/bin/env bash
#
# Creates the kind cluster (if it doesn't already exist) and sets the
# kubectl context. No prerequisites: this is the first step in the chain.
#
# Optional variables:
#   CLUSTER_CONFIG_FILE kind config file to use as-is. Takes priority over
#       CONTROL_PLANE_COUNT/WORKER_COUNT/NODE_IMAGE: if set, those three are
#       simply ignored (with a warning if any of them was also set) rather
#       than generating a config, so callers can leave them in place (e.g.
#       job-level CI env vars reused by other steps) without needing to
#       blank them out just to let CLUSTER_CONFIG_FILE win.
#   CONTROL_PLANE_COUNT / WORKER_COUNT / NODE_IMAGE
#       used only when CLUSTER_CONFIG_FILE is unset: generate the config on
#       the fly, defaulting whichever of the three is not set.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"

step_cluster() {
    local default_cluster_config_file="k8s/cluster-config.yaml"
    local default_control_plane_count=1
    local default_worker_count=5
    local default_node_image="kindest/node:v1.34.8@sha256:02722c2dedddcfc00febf5d27fbeb9b7b2c14294c82109ff4a85d89ac9ba3256"
    local generated_cluster_config_file="/tmp/${CLUSTER_NAME}-cluster-config.generated.yaml"

    local cluster_config_file
    if [[ -n "${CLUSTER_CONFIG_FILE:-}" ]]; then
        if [[ -n "${CONTROL_PLANE_COUNT:-}${WORKER_COUNT:-}${NODE_IMAGE:-}" ]]; then
            warn "CLUSTER_CONFIG_FILE is set, ignoring CONTROL_PLANE_COUNT/WORKER_COUNT/NODE_IMAGE"
        fi
        cluster_config_file="$CLUSTER_CONFIG_FILE"
    elif [[ -n "${CONTROL_PLANE_COUNT:-}${WORKER_COUNT:-}${NODE_IMAGE:-}" ]]; then
        local control_plane_count="${CONTROL_PLANE_COUNT:-$default_control_plane_count}"
        local worker_count="${WORKER_COUNT:-$default_worker_count}"
        local node_image="${NODE_IMAGE:-$default_node_image}"

        log "Generating kind cluster config: $control_plane_count control-plane, $worker_count worker(s), image '$node_image'"

        local nodes_yaml=""
        for ((i = 0; i < control_plane_count; i++)); do
            nodes_yaml+="  - role: control-plane
    image: ${node_image}
"
        done
        for ((i = 0; i < worker_count; i++)); do
            nodes_yaml+="  - role: worker
    image: ${node_image}
"
        done

        cat >"$generated_cluster_config_file" <<EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
${nodes_yaml}
EOF

        cluster_config_file="$generated_cluster_config_file"
    else
        cluster_config_file="$default_cluster_config_file"
    fi

    log "Checking for existing kind cluster '$CLUSTER_NAME'"
    if kind get clusters | grep -qx "$CLUSTER_NAME"; then
        log "Kind cluster '$CLUSTER_NAME' already exists"
        log "Exporting kubeconfig for existing cluster '$CLUSTER_NAME'"
        kind export kubeconfig --name "$CLUSTER_NAME"
    else
        log "Creating kind cluster '$CLUSTER_NAME' using config '$cluster_config_file'"
        kind create cluster --name "$CLUSTER_NAME" --config "$cluster_config_file"
    fi

    rm -f "$generated_cluster_config_file"

    local expected_context="kind-${CLUSTER_NAME}"
    local current_context
    current_context="$(kubectl config current-context)"

    if [[ "$current_context" != "$expected_context" ]]; then
        log "Switching kubectl context to '$expected_context'"
        kubectl config use-context "$expected_context"
    fi
}

# Run the step if this script is executed directly, not sourced
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    setup_error_trap
    require_command kind
    require_command kubectl
    step_cluster
    log "Cluster ready"
    kubectl get nodes -o wide
fi
