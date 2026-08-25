#!/usr/bin/env bash
#
# Initializes the whole cluster by running, in order, all the steps defined
# in scripts/steps/. Every step is also executable on its own: see the
# header of each file in scripts/steps/ for its prerequisites and the
# optional variables it accepts.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STEPS_DIR="$SCRIPT_DIR/steps"

source "$SCRIPT_DIR/common.sh"

setup_error_trap

log "k8s-init: starting cluster setup"

require_command kind
require_command kubectl
require_command helm

source "$STEPS_DIR/cluster.sh"
source "$STEPS_DIR/headlamp.sh"
source "$STEPS_DIR/plg-stack.sh"
source "$STEPS_DIR/namespaces-crds.sh"
source "$STEPS_DIR/gatekeeper.sh"
source "$STEPS_DIR/cloudnative-pg.sh"
source "$STEPS_DIR/node-controller.sh"
source "$STEPS_DIR/dataset-service.sh"
source "$STEPS_DIR/context-service.sh"
source "$STEPS_DIR/task-request-controller.sh"
source "$STEPS_DIR/scheduler.sh"

step_cluster
step_headlamp
step_plg_stack
step_namespaces_crds
step_gatekeeper
step_cloudnative_pg
step_node_controller
step_dataset_service
step_context_service
step_task_request_controller
step_scheduler

log "Cluster nodes information:"
kubectl get nodes -o wide

log "Cluster initialized successfully!"
