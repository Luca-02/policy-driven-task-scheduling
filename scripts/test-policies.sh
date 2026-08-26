#!/usr/bin/env bash
#
# Runs the policy tests defined under k8s/policies.
#
# Two kinds of tests exist:
#   - Self-contained policies (those with a tests/suite.yaml) are verified
#     offline with `gator verify`.
#   - Policies backed by an external data provider (e.g.
#     validate-task-request-datasets) have no suite.yaml, since gator cannot
#     evaluate them offline. These are tested manually: `kubectl apply` each
#     file under their tests/ directory against a live cluster and check
#     that it is rejected, as described by the comments in that file.
#     Requires an initialized and populated cluster
#     (scripts/init-cluster.sh + scripts/populate-examples.sh).
#
# Usage: ./scripts/test-policies.sh [gator|manual|all]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

# common.sh enables "set -e", but this script relies on continuing past
# expected failures (a rejected kubectl apply, a failing gator suite) and
# tallying them in FAILURES instead of aborting. It also runs commands like
# `grep -n '#' "$test_file"` outside of any if/while guard, which would kill
# the script under errexit if a test file had no matching comment lines.
# Restore the original semantics: keep -u and pipefail (already set by
# common.sh), drop -e.
set +e

readonly POLICIES_DIR="k8s/policies"
readonly MODE="${1:-all}"

FAILURES=0

run_gator_suites() {
    require_command gator

    local suite_file policy_dir policy_name

    while IFS= read -r suite_file; do
        policy_dir="$(dirname "$(dirname "$suite_file")")"
        policy_name="$(basename "$policy_dir")"

        log "Running gator suite for '$policy_name'"
        if gator verify "$suite_file"; then
            log "PASS: $policy_name"
        else
            error "FAIL: $policy_name"
            FAILURES=$((FAILURES + 1))
        fi
    done < <(find "$POLICIES_DIR" -type f -name "suite.yaml" | sort)
}

run_manual_tests() {
    require_command kubectl

    log "Checking connectivity to the Kubernetes cluster"
    if ! kubectl cluster-info >/dev/null 2>&1; then
        error "No reachable Kubernetes cluster. Run scripts/init-cluster.sh and scripts/populate-examples.sh first."
        exit 1
    fi

    local policy_dir policy_name suite_file tests_dir test_file case_name output

    for policy_dir in "$POLICIES_DIR"/*/; do
        policy_dir="${policy_dir%/}"
        suite_file="$policy_dir/tests/suite.yaml"
        tests_dir="$policy_dir/tests"

        # Policies with a suite.yaml are covered by gator, skip them here.
        [[ -f "$suite_file" ]] && continue
        [[ -d "$tests_dir" ]] || continue

        policy_name="$(basename "$policy_dir")"
        log "Manually testing policy '$policy_name' (requires external data provider + live cluster)"

        for test_file in "$tests_dir"/*.yaml; do
            [[ -f "$test_file" ]] || continue
            case_name="$(basename "$test_file" .yaml)"

            log "Applying '$case_name' ($test_file) - expecting the request to be denied"

            if output=$(kubectl apply -f "$test_file" 2>&1); then
                error "FAIL: '$case_name' was unexpectedly accepted by the cluster"
                FAILURES=$((FAILURES + 1))
            else
                log "PASS: '$case_name' was denied as expected"
                printf "  Denial message:\n"
                printf "%s\n" "$output" | sed 's/^/    /'
            fi

            printf "\n  Expected reason (from '%s' comments):\n" "$test_file"
            grep -n '#' "$test_file" | sed 's/^/    /'
            printf "\n"
        done
    done
}

case "$MODE" in
    gator)
        run_gator_suites
        ;;
    manual)
        run_manual_tests
        ;;
    all)
        run_gator_suites
        run_manual_tests
        ;;
    *)
        error "Unknown mode '$MODE'. Usage: $0 [gator|manual|all]"
        exit 1
        ;;
esac

if [[ "$FAILURES" -gt 0 ]]; then
    error "$FAILURES test(s) failed"
    exit 1
fi

log "All tests passed"