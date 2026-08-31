#!/usr/bin/env bash
#
# Initializes the whole cluster by running, in order, all the steps defined
# in scripts/steps/. Every step is also executable on its own: see the
# header of each file in scripts/steps/ for its prerequisites and the
# optional variables it accepts.
# 
# Usage: CLUSTER_NAME=<cluster_name> \
#   CLUSTER_CONFIG_FILE=<cluster_config_file> \
#   CONTROL_PLANE_COUNT=<control_plane_count> \
#   WORKER_COUNT=<worker_count> \
#   NODE_IMAGE=<node_image> \
#   ENABLE_DASHBOARD=<true|false> \
#   ENABLE_MONITORING=<true|false> \
#   DATASET_SERVICE_LIGHT_MODE=<true|false> \
#   CONTEXT_SERVICE_LIGHT_MODE=<true|false> \
#   bash ./scripts/init-cluster.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STEPS_DIR="$SCRIPT_DIR/steps"

source "$SCRIPT_DIR/common.sh"

setup_error_trap

log "k8s-init: starting cluster setup"

require_command kind
require_command kubectl
require_command helm

ENABLE_MONITORING="${ENABLE_MONITORING:-true}"
ENABLE_DASHBOARD="${ENABLE_DASHBOARD:-true}"

source "$STEPS_DIR/cluster.sh"
source "$STEPS_DIR/headlamp.sh"
source "$STEPS_DIR/monitoring-stack.sh"
source "$STEPS_DIR/namespaces-crds.sh"
source "$STEPS_DIR/gatekeeper.sh"
source "$STEPS_DIR/cloudnative-pg.sh"
source "$STEPS_DIR/node-controller.sh"
source "$STEPS_DIR/dataset-service.sh"
source "$STEPS_DIR/context-service.sh"
source "$STEPS_DIR/task-request-controller.sh"
source "$STEPS_DIR/scheduler.sh"

#######################################
# Run steps in order
#######################################

step_cluster

if [[ "${ENABLE_DASHBOARD}" == "true" ]]; then
    step_headlamp
else
    log "Skipping Headlamp (dashboard) installation"
fi

if [[ "${ENABLE_MONITORING}" == "true" ]]; then
    step_monitoring_stack
else
    log "Skipping Monitoring stack installation"
fi

step_namespaces_crds
step_gatekeeper

if [[ "$DATASET_SERVICE_LIGHT_MODE" == "true" && "$CONTEXT_SERVICE_LIGHT_MODE" == "true" ]]; then
    log "All services are in light mode, skipping CloudNativePG installation"
else
    log "At least one service is not in light mode, installing CloudNativePG"
    step_cloudnative_pg
fi

step_node_controller
step_dataset_service
step_context_service
step_task_request_controller
step_scheduler

log "Cluster nodes information:"
kubectl get nodes -o wide

log "Cluster initialized successfully!"
