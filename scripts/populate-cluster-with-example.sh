#!/usr/bin/env bash

set -euo pipefail

readonly NODE_PROPERTY_DIR="k8s/examples/node-property"
readonly GEOGRAPHICAL_GROUP_DIR="k8s/examples/geographical-group"

echo "Populate with node properties"
kubectl apply -f "${NODE_PROPERTY_DIR}"

echo "Populate with geographical groups"
kubectl apply -f "${GEOGRAPHICAL_GROUP_DIR}"

echo "Seeding dataset-service"
(
    readonly DATASET_SERVICE_DIR="dataset-service"
    readonly DATASET_SERVICE_NAMESPACE="dataset-service"
    readonly SEED_FILE="data/seed.json"

    cd "${DATASET_SERVICE_DIR}"

    kubectl create configmap dataset-seed \
        --from-file=seed.json="${SEED_FILE}" \
        --namespace "${DATASET_SERVICE_NAMESPACE}" \
        --dry-run=client -o yaml | kubectl apply -f -

    kubectl delete job dataset-seeding \
        --namespace "${DATASET_SERVICE_NAMESPACE}" \
        --ignore-not-found

    kubectl apply -f k8s/seeding.yaml
    kubectl wait --namespace dataset-service \
        --for=condition=complete \
        job/dataset-seeding \
        --timeout=60s
)