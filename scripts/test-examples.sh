#!/usr/bin/env bash
#
# End-to-end test of the scheduling pipeline against the example
# TaskRequests in examples/task-request/, using the cluster state seeded by
# scripts/populate-cluster-with-example.sh (node properties, geographical
# groups, context-service and dataset-service data, see
# examples/cluster-config.yaml and examples/data/*.json).
#
# For each example this submits the TaskRequest, waits for its terminal
# outcome and checks it against the expectation documented in the comments
# of the corresponding examples/task-request/*.yaml file:
#   - invalid.yaml: `kubectl apply` itself must be denied by the Gatekeeper
#     validation webhook (structural errors, non-existent references, and
#     a c_auth violation).
#   - emptygeostar.yaml / emptystaticnodes.yaml: the request is admitted,
#     but the task-request-controller rejects it (status.phase=Failed)
#     because geo*(t) / the static dataset node intersection is empty.
#   - t1.yaml / t1static.yaml: the request is admitted and scheduled
#     (status.phase=Scheduled), and the resulting Pod lands on the
#     specific node predicted by the thesis's worked examples.
#   - twallford.yaml / twallfordreuse.yaml / twallferrari.yaml: exercise
#     c_wall. wallford.yaml must run first to deposit Lambda(kind-worker)
#     <- {Ford}; wallfordreuse.yaml (same context) is then scheduled on
#     the same node, while wallferrari.yaml (conflicting context) is
#     admitted but left permanently unschedulable -- until the manual
#     sanitization Job (node-controller/k8s/sanitize.yaml) clears
#     Lambda(kind-worker), at which point wallferrari.yaml's Pod is
#     scheduled and its Job reaches phase=Complete.
#
# Requires an initialized and populated cluster:
#   scripts/init-cluster.sh && scripts/populate-cluster-with-example.sh
#
# Usage: ./scripts/test-example.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

# common.sh enables "set -e", but this script needs to keep going past
# expected failures (a denied kubectl apply, a wrong phase/node) and tally
# them in FAILURES instead of aborting on the first mismatch.
set +e

readonly TASK_REQUEST_DIR="examples/task-request"
readonly NAMESPACE="compute"
readonly PHASE_TIMEOUT="${PHASE_TIMEOUT:-90}"
readonly SCHEDULE_TIMEOUT="${SCHEDULE_TIMEOUT:-90}"
readonly UNSCHEDULABLE_WAIT="${UNSCHEDULABLE_WAIT:-20}"

readonly NODE_CONTROLLER_NAMESPACE="node-controller"
readonly NODE_CONTROLLER_DEPLOYMENT="node-controller"
readonly NODE_CONTROLLER_CONTAINER="node-controller"
readonly SANITIZE_INTERVAL_DEFAULT="60"
readonly NODE_SANITIZE_JOB_MANIFEST="node-controller/k8s/sanitize.yaml"
readonly NODE_SANITIZE_JOB_NAME="node-sanitize-manual"
readonly COMPLETE_TIMEOUT="${COMPLETE_TIMEOUT:-90}"

FAILURES=0
ORIGINAL_SANITIZE_INTERVAL=""
SANITIZATION_DISABLED=0

pass() {
    log "PASS: $*"
}

fail() {
    error "FAIL: $*"
    FAILURES=$((FAILURES + 1))
}

check_cluster_ready() {
    require_command kubectl

    log "Checking connectivity to the Kubernetes cluster"
    if ! kubectl cluster-info >/dev/null 2>&1; then
        error "No reachable Kubernetes cluster. Run scripts/init-cluster.sh and scripts/populate-cluster-with-example.sh first."
        exit 1
    fi

    if ! resource_exists get namespace "$NAMESPACE"; then
        error "Namespace '$NAMESPACE' not found. Run scripts/init-cluster.sh and scripts/populate-cluster-with-example.sh first."
        exit 1
    fi
}

# twallferrari.yaml is only guaranteed to stay Scheduled/unschedulable
# forever if node-controller's periodic sanitization (Algorithm Sanitize(n),
# see sec. 3.9) never runs during the test: once kind-worker's Job from
# wallford.yaml completes, the node has no active Pods left and becomes a
# candidate for sanitization, which would clear Lambda(kind-worker) and let
# wallferrari become schedulable after all. Setting
# SANITIZE_INTERVAL_SECONDS=0 disables the periodic kopf.timer entirely
# (see node-controller/main.py), keeping the {Ford} residue in place for
# the whole run. The original value is restored on exit via the trap below.
disable_node_sanitization() {
    log "Disabling automatic node sanitization on '$NODE_CONTROLLER_DEPLOYMENT' for the duration of this test run"

    if ! resource_exists -n "$NODE_CONTROLLER_NAMESPACE" get deployment "$NODE_CONTROLLER_DEPLOYMENT"; then
        warn "Deployment '$NODE_CONTROLLER_DEPLOYMENT' not found in namespace '$NODE_CONTROLLER_NAMESPACE', skipping"
        return
    fi

    ORIGINAL_SANITIZE_INTERVAL="$(kubectl -n "$NODE_CONTROLLER_NAMESPACE" get deployment "$NODE_CONTROLLER_DEPLOYMENT" \
        -o jsonpath="{.spec.template.spec.containers[?(@.name==\"$NODE_CONTROLLER_CONTAINER\")].env[?(@.name==\"SANITIZE_INTERVAL_SECONDS\")].value}" 2>/dev/null)"
    [[ -z "$ORIGINAL_SANITIZE_INTERVAL" ]] && ORIGINAL_SANITIZE_INTERVAL="$SANITIZE_INTERVAL_DEFAULT"
    log "Current SANITIZE_INTERVAL_SECONDS='$ORIGINAL_SANITIZE_INTERVAL', will restore it on exit"

    kubectl -n "$NODE_CONTROLLER_NAMESPACE" set env "deployment/$NODE_CONTROLLER_DEPLOYMENT" \
        SANITIZE_INTERVAL_SECONDS=0 >/dev/null
    wait_for_deployment "$NODE_CONTROLLER_NAMESPACE" "$NODE_CONTROLLER_DEPLOYMENT" 120s
    SANITIZATION_DISABLED=1
}

restore_node_sanitization() {
    [[ "$SANITIZATION_DISABLED" -eq 1 ]] || return 0

    log "Restoring node-controller sanitization interval to '${ORIGINAL_SANITIZE_INTERVAL}'"
    kubectl -n "$NODE_CONTROLLER_NAMESPACE" set env "deployment/$NODE_CONTROLLER_DEPLOYMENT" \
        SANITIZE_INTERVAL_SECONDS="$ORIGINAL_SANITIZE_INTERVAL" >/dev/null 2>&1 || \
        warn "Failed to restore SANITIZE_INTERVAL_SECONDS on '$NODE_CONTROLLER_DEPLOYMENT', please check manually"
    wait_for_deployment "$NODE_CONTROLLER_NAMESPACE" "$NODE_CONTROLLER_DEPLOYMENT" 120s || true
}

# Deletes a TaskRequest (if present) and waits until its owned Job and Pods
# are actually gone, so that a subsequent re-apply of the same example
# always creates a fresh Job instead of racing the garbage collector.
reset_task_request() {
    local name="$1"
    local i

    kubectl -n "$NAMESPACE" delete taskrequest "$name" --ignore-not-found >/dev/null 2>&1

    for i in $(seq 1 30); do
        if ! resource_exists -n "$NAMESPACE" get job "$name"; then
            break
        fi
        sleep 1
    done
    kubectl -n "$NAMESPACE" delete job "$name" --ignore-not-found --wait=true --timeout=30s >/dev/null 2>&1

    for i in $(seq 1 30); do
        if [[ -z "$(kubectl -n "$NAMESPACE" get pods -l job-name="$name" -o name 2>/dev/null)" ]]; then
            return 0
        fi
        sleep 1
    done
    warn "Pod(s) for '$name' still present after reset, continuing anyway"
}

# Polls status.phase of a TaskRequest until it reaches one of the given
# target phases (space-separated) or the timeout expires. Echoes the last
# observed phase.
wait_for_phase() {
    local name="$1"
    local targets="$2"
    local timeout="${3:-$PHASE_TIMEOUT}"
    local phase target i

    for i in $(seq 1 "$timeout"); do
        phase="$(kubectl -n "$NAMESPACE" get taskrequest "$name" -o jsonpath='{.status.phase}' 2>/dev/null)"
        for target in $targets; do
            if [[ "$phase" == "$target" ]]; then
                echo "$phase"
                return 0
            fi
        done
        sleep 1
    done

    echo "$phase"
    return 1
}

task_request_message() {
    local name="$1"
    kubectl -n "$NAMESPACE" get taskrequest "$name" -o jsonpath='{.status.message}' 2>/dev/null
}

# Polls until the (single) Pod owned by the Job named after the TaskRequest
# is assigned a node, or the timeout expires. Echoes the node name.
wait_for_scheduled_node() {
    local name="$1"
    local timeout="${2:-$SCHEDULE_TIMEOUT}"
    local node i

    for i in $(seq 1 "$timeout"); do
        node="$(kubectl -n "$NAMESPACE" get pods -l job-name="$name" -o jsonpath='{.items[0].spec.nodeName}' 2>/dev/null)"
        if [[ -n "$node" ]]; then
            echo "$node"
            return 0
        fi
        sleep 1
    done

    echo ""
    return 1
}

#######################################
# Expectation helpers, one per outcome documented in examples/task-request/
#######################################

# The request itself must be denied by the Gatekeeper validation webhook:
# `kubectl apply` fails and no TaskRequest is ever created.
expect_denied_by_gatekeeper() {
    local file="$1"
    local name
    name="$(basename "$file" .yaml)"
    local output

    log "Applying '$name' ($file) - expecting denial by the validation webhook"
    if output=$(kubectl apply -f "$file" 2>&1); then
        fail "'$name' was unexpectedly accepted by the cluster"
        kubectl delete -f "$file" --ignore-not-found >/dev/null 2>&1
    else
        pass "'$name' was denied at admission as expected"
        printf "  Denial message:\n%s\n" "$output" | sed 's/^/    /'
    fi
}

# The request is admitted, but the task-request-controller rejects it:
# status.phase must reach Failed.
expect_rejected_by_controller() {
    local file="$1"
    local name
    name="$(basename "$file" .yaml)"
    local phase

    reset_task_request "$name"

    log "Applying '$name' ($file) - expecting admission followed by phase=Failed"
    if ! kubectl apply -f "$file" >/dev/null; then
        fail "'$name' was unexpectedly denied at admission"
        return
    fi

    phase="$(wait_for_phase "$name" "Failed Scheduled")"
    if [[ "$phase" == "Failed" ]]; then
        pass "'$name' reached phase=Failed as expected"
        log "  Reason: $(task_request_message "$name")"
    else
        fail "'$name' expected phase=Failed, got '${phase:-<empty/timeout>}'"
    fi
}

# The request is admitted and scheduled, and the resulting Pod must land on
# the given node.
expect_scheduled_on() {
    local file="$1"
    local expected_node="$2"
    local name
    name="$(basename "$file" .yaml)"
    local phase node

    reset_task_request "$name"

    log "Applying '$name' ($file) - expecting phase=Scheduled, Pod on '$expected_node'"
    if ! kubectl apply -f "$file" >/dev/null; then
        fail "'$name' was unexpectedly denied at admission"
        return
    fi

    phase="$(wait_for_phase "$name" "Scheduled Failed")"
    if [[ "$phase" != "Scheduled" ]]; then
        fail "'$name' expected phase=Scheduled, got '${phase:-<empty/timeout>}' ($(task_request_message "$name"))"
        return
    fi

    node="$(wait_for_scheduled_node "$name")"
    if [[ -z "$node" ]]; then
        fail "'$name' Pod was never assigned a node within ${SCHEDULE_TIMEOUT}s"
    elif [[ "$node" == "$expected_node" ]]; then
        pass "'$name' scheduled on '$node' as expected"
    else
        fail "'$name' expected to be scheduled on '$expected_node', got '$node'"
    fi
}

# The request is admitted (Job created, phase=Scheduled) but must remain
# permanently unschedulable: no node ever satisfies c_wall for it.
expect_admitted_but_unschedulable() {
    local file="$1"
    local name
    name="$(basename "$file" .yaml)"
    local phase node pod

    reset_task_request "$name"

    log "Applying '$name' ($file) - expecting phase=Scheduled but the Pod to stay unschedulable"
    if ! kubectl apply -f "$file" >/dev/null; then
        fail "'$name' was unexpectedly denied at admission"
        return
    fi

    phase="$(wait_for_phase "$name" "Scheduled Failed")"
    if [[ "$phase" != "Scheduled" ]]; then
        fail "'$name' expected phase=Scheduled, got '${phase:-<empty/timeout>}' ($(task_request_message "$name"))"
        return
    fi

    log "Waiting ${UNSCHEDULABLE_WAIT}s to confirm the Pod stays Pending/unschedulable"
    sleep "$UNSCHEDULABLE_WAIT"

    node="$(kubectl -n "$NAMESPACE" get pods -l job-name="$name" -o jsonpath='{.items[0].spec.nodeName}' 2>/dev/null)"
    pod="$(kubectl -n "$NAMESPACE" get pods -l job-name="$name" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)"

    if [[ -z "$pod" ]]; then
        fail "'$name' Pod not found"
        return
    fi
    if [[ -n "$node" ]]; then
        fail "'$name' expected to remain unschedulable, but was scheduled on '$node'"
        return
    fi

    pass "'$name' remained unschedulable as expected (Pod '$pod' still Pending)"
    log "  FailedScheduling events for '$pod':"
    kubectl -n "$NAMESPACE" get events \
        --field-selector involvedObject.name="$pod",reason=FailedScheduling \
        -o jsonpath='{range .items[*]}    {.message}{"\n"}{end}' 2>/dev/null
}

# Runs node-controller/k8s/sanitize.yaml to completion: a one-shot Job that
# runs Algorithm Sanitize(n) for every non-control-plane node, clearing
# Lambda(n) wherever it isn't empty. Re-applies from scratch every call so
# repeated runs of this script don't collide with a leftover completed Job
# of the same name.
run_manual_sanitization() {
    log "Running manual node sanitization ($NODE_SANITIZE_JOB_MANIFEST) to clear residual context traces"

    kubectl -n "$NODE_CONTROLLER_NAMESPACE" delete job "$NODE_SANITIZE_JOB_NAME" \
        --ignore-not-found --wait=true --timeout=60s >/dev/null 2>&1

    if ! kubectl apply -f "$NODE_SANITIZE_JOB_MANIFEST" >/dev/null; then
        fail "could not apply $NODE_SANITIZE_JOB_MANIFEST"
        return 1
    fi

    if ! kubectl -n "$NODE_CONTROLLER_NAMESPACE" wait --for=condition=complete \
        "job/$NODE_SANITIZE_JOB_NAME" --timeout=120s >/dev/null 2>&1; then
        fail "manual sanitization Job '$NODE_SANITIZE_JOB_NAME' did not complete"
        kubectl -n "$NODE_CONTROLLER_NAMESPACE" logs "job/$NODE_SANITIZE_JOB_NAME" --tail=100 2>&1 | sed 's/^/    /'
        return 1
    fi

    pass "manual sanitization Job '$NODE_SANITIZE_JOB_NAME' completed"
    return 0
}

# For a TaskRequest already Scheduled-but-unschedulable, waits for its Pod
# to finally be bound (now that whatever blocked it, e.g. c_wall, has been
# cleared) on the given node, and for the TaskRequest to then reach
# phase=Complete.
expect_eventually_completed() {
    local file="$1"
    local expected_node="$2"
    local name
    name="$(basename "$file" .yaml)"
    local node phase

    log "Waiting for '$name' Pod to be scheduled onto '$expected_node' now that the block is cleared"
    node="$(wait_for_scheduled_node "$name")"
    if [[ -z "$node" ]]; then
        fail "'$name' Pod was never scheduled after sanitization (within ${SCHEDULE_TIMEOUT}s)"
        return
    fi
    if [[ "$node" != "$expected_node" ]]; then
        fail "'$name' expected to be scheduled on '$expected_node' after sanitization, got '$node'"
        return
    fi
    pass "'$name' scheduled on '$node' after sanitization"

    phase="$(wait_for_phase "$name" "Complete Failed" "$COMPLETE_TIMEOUT")"
    if [[ "$phase" == "Complete" ]]; then
        pass "'$name' reached phase=Complete as expected"
    else
        fail "'$name' expected phase=Complete after sanitization, got '${phase:-<empty/timeout>}' ($(task_request_message "$name"))"
    fi
}

#######################################
# Test plan
#######################################

check_cluster_ready

trap restore_node_sanitization EXIT
disable_node_sanitization

log "=== invalid.yaml: rejected by Gatekeeper at admission ==="
expect_denied_by_gatekeeper "$TASK_REQUEST_DIR/invalid.yaml"

log "=== emptygeostar.yaml: geo*(t) empty -> rejected by the controller ==="
expect_rejected_by_controller "$TASK_REQUEST_DIR/emptygeostar.yaml"

log "=== emptystaticnodes.yaml: static dataset intersection empty -> rejected by the controller ==="
expect_rejected_by_controller "$TASK_REQUEST_DIR/emptystaticnodes.yaml"

log "=== t1.yaml: c_prop/c_geo/phi_transfer tie-break -> kind-worker ==="
expect_scheduled_on "$TASK_REQUEST_DIR/t1.yaml" "kind-worker"

log "=== t1static.yaml: c_static ties transfer, phi_prop decides -> kind-worker4 ==="
expect_scheduled_on "$TASK_REQUEST_DIR/t1static.yaml" "kind-worker4"

log "=== twallford.yaml: deposits Lambda(kind-worker) <- {Ford} ==="
expect_scheduled_on "$TASK_REQUEST_DIR/twallford.yaml" "kind-worker"

log "=== twallfordreuse.yaml: same context reuses kind-worker ==="
expect_scheduled_on "$TASK_REQUEST_DIR/twallfordreuse.yaml" "kind-worker"

log "=== twallferrari.yaml: conflicting context -> admitted but unschedulable ==="
expect_admitted_but_unschedulable "$TASK_REQUEST_DIR/twallferrari.yaml"

log "=== manual sanitization: clears Lambda(kind-worker), wallferrari should then complete ==="
if run_manual_sanitization; then
    expect_eventually_completed "$TASK_REQUEST_DIR/twallferrari.yaml" "kind-worker"
fi

if [[ "$FAILURES" -gt 0 ]]; then
    error "$FAILURES test(s) failed"
    exit 1
fi

log "All example tests passed"
