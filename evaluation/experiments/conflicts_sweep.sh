#!/usr/bin/env bash
#
# Fixed across all points: K contexts, sanitize interval (the optimum found by
# the sanitize experiment), task count/rate, nodes, task duration. The ONLY
# independent variable is the conflict density rho.
#
# Usage (from the evaluation/ directory):
#   bash experiments/conflicts_sweep.sh
#
# Override any knob via environment variables, e.g.:
#   INTERVAL=10 DENSITIES="0 0.1 0.2 0.3 0.4 0.5 0.6 0.7" REPLICAS=5 bash experiments/conflicts_sweep.sh

set -euo pipefail

# --- Fixed scenario parameters (same for every point in the sweep) ---------- #
SEED="${SEED:-42}"
CONTEXTS="${CONTEXTS:-10}"
INTERVAL="${INTERVAL:-10}"
TASKS="${TASKS:-100}"
RATE="${RATE:-1.0}"
TASK_DURATION="${TASK_DURATION:-10}"
NODES="${NODES:-kind-worker kind-worker2 kind-worker3 kind-worker4 kind-worker5}"
REPLICAS="${REPLICAS:-5}"
TASK_TTL="${TASK_TTL:-}"

# --- Independent variable: the conflict density grid ------------------------ #
DENSITIES="${DENSITIES:-0 0.1 0.2 0.3 0.4 0.5 0.6 0.7}"

# --- Warm-up: pre-pull the task image on every node ------------------------- #
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

# Scenario names cannot contain '.', so 0.05 -> conflicts-rho005, 0.8 -> rho080.
scenario_name() {
    local rho="$1"
    local pct
    pct=$(python3 -c "print(f'{round(float(\"$rho\")*100):03d}')")
    echo "conflicts-rho${pct}"
}

echo "=== conflict-density sweep ==="
echo "K=$CONTEXTS interval=${INTERVAL}s N=$TASKS rate=${RATE}s duration=${TASK_DURATION}s replicas=$REPLICAS"
echo "densities: $DENSITIES | task_ttl: ${TASK_TTL:-none}"
echo

prepull_image

TTL_FLAG=()
if [[ -n "$TASK_TTL" ]]; then
    TTL_FLAG=(--task-ttl-seconds "$TASK_TTL")
fi

for rho in $DENSITIES; do
    name=$(scenario_name "$rho")
    echo "--- ${name} (conflict_density=${rho}) ---"

    python generate.py \
        --name "$name" \
        --seed "$SEED" \
        --contexts "$CONTEXTS" \
        --conflict-density "$rho" \
        --tasks "$TASKS" \
        --rate-seconds "$RATE" \
        --sanitize-interval-seconds "$INTERVAL" \
        --task-duration-seconds "$TASK_DURATION" \
        --nodes $NODES \
        --replicas "$REPLICAS" \
        "${TTL_FLAG[@]+"${TTL_FLAG[@]}"}" \
        --out scenarios

    # setup.py reseeds the conflict pairs and (re)applies the fixed knobs; done
    # once per scenario since the cluster configuration is identical across
    # its replicas.
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

echo "=== sweep done. Results under results/conflicts-rho<pct>/run_<r>/ ==="