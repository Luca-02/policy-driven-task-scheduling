#!/usr/bin/env bash
#
# sanitize_sweep.sh — Run the "Impatto della sanificazione" experiment (5.4).
#
# Fixed across all points: K contexts, conflict density, task count/rate, nodes,
# task duration. The ONLY independent variable is SANITIZE_INTERVAL_SECONDS.
# This isolates the interval's effect, as the methodology requires.
#
# Usage (from the evaluation/ directory):
#   bash experiments/sanitize_sweep.sh
#
# Override any knob via environment variables, e.g.:
#   REPLICAS=5 INTERVALS="1 5 10 20 30 60 90 120" bash experiments/sanitize_sweep.sh
#
set -euo pipefail

# --- Fixed scenario parameters (same for every point in the sweep) ---------- #
SEED="${SEED:-10}"
CONTEXTS="${CONTEXTS:-10}"
DENSITY="${DENSITY:-0.5}"
TASKS="${TASKS:-30}"
RATE="${RATE:-1.0}"
TASK_DURATION="${TASK_DURATION:-10}"
NODES="${NODES:-kind-worker kind-worker2 kind-worker3 kind-worker4 kind-worker5}"
REPLICAS="${REPLICAS:-5}"

# --- Independent variable: the interval grid --------------------------------- #
INTERVALS="${INTERVALS:-1 5 10 20 30 45 60 90 120}"

# --- Warm-up: pre-pull the task image on every node ------------------------- #
# The only cold-start cost is the first pull of busybox on each node, which
# would inflate startup_s (and thus latency) on the first scenario only. A brief
# DaemonSet pulls the image everywhere once, so the sweep does not waste a whole
# discarded run to warm caches.
BASELINE_IMAGE="${BASELINE_IMAGE:-busybox:musl}"
TASK_NAMESPACE="${TASK_NAMESPACE:-compute}"

prepull_image() {
    echo "--- warm-up: pre-pulling ${BASELINE_IMAGE} on all nodes ---"
    kubectl apply -n "$TASK_NAMESPACE" -f - <<EOF >/dev/null
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: eval-image-prepull
spec:
  selector:
    matchLabels: { app: eval-image-prepull }
  template:
    metadata:
      labels: { app: eval-image-prepull }
    spec:
      containers:
        - name: pause
          image: ${BASELINE_IMAGE}
          command: ["sh", "-c", "sleep 3600"]
EOF
    kubectl rollout status -n "$TASK_NAMESPACE" ds/eval-image-prepull --timeout=180s || true
    kubectl delete ds -n "$TASK_NAMESPACE" eval-image-prepull --ignore-not-found >/dev/null
    echo "warm-up done"
    echo
}

echo "=== sanitize-interval sweep ==="
echo "K=$CONTEXTS rho=$DENSITY N=$TASKS rate=${RATE}s duration=${TASK_DURATION}s replicas=$REPLICAS"
echo "intervals: $INTERVALS"
echo

prepull_image

for interval in $INTERVALS; do
    name="sanitize-${interval}"
    echo "--- ${name} (SANITIZE_INTERVAL_SECONDS=${interval}) ---"

    python generate.py \
        --name "$name" \
        --seed "$SEED" \
        --contexts "$CONTEXTS" \
        --conflict-density "$DENSITY" \
        --tasks "$TASKS" \
        --rate-seconds "$RATE" \
        --sanitize-interval-seconds "$interval" \
        --task-duration-seconds "$TASK_DURATION" \
        --nodes $NODES \
        --replicas "$REPLICAS" \
        --out scenarios

    # setup.py restarts the node-controller with this interval; done once per
    # scenario, not per replica, since the cluster configuration is identical
    # across replicas of the same scenario.
    python setup.py --scenario "scenarios/${name}"

    for ((r = 0; r < REPLICAS; r++)); do
        echo "  replica $r"
        python clean.py --scenario "scenarios/${name}"
        python run.py \
            --scenario "scenarios/${name}" \
            --replica "$r" \
            --timeout-seconds 0
    done
    echo
done

echo "=== sweep done. Results under results/sanitize-<interval>/run_<r>/ ==="