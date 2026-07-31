#!/usr/bin/env bash

set -euo pipefail

readonly NODE_PROPERTY_DIR="examples/node-property"
readonly GEOGRAPHICAL_GROUP_DIR="examples/geographical-group"

echo "Populate with node properties"
kubectl apply -f "${NODE_PROPERTY_DIR}"

echo "Populate with geographical groups"
kubectl apply -f "${GEOGRAPHICAL_GROUP_DIR}"

echo "Populate context-service"
(
    readonly CONTEXT_SERVICE_DIR="context-service"
    readonly CONTEXT_SERVICE_NAMESPACE="context-service"
    readonly SEED_FILE="data/seed.json"

    cd "${CONTEXT_SERVICE_DIR}"

    kubectl create configmap context-seed \
        --from-file=seed.json="${SEED_FILE}" \
        --namespace "${CONTEXT_SERVICE_NAMESPACE}" \
        --dry-run=client -o yaml | kubectl apply -f -

    kubectl delete job context-seeding \
        --namespace "${CONTEXT_SERVICE_NAMESPACE}" \
        --ignore-not-found

    kubectl apply -f k8s/seeding.yaml
    kubectl wait --namespace context-service \
        --for=condition=complete \
        job/context-seeding \
        --timeout=60s

    kubectl delete configmap context-seed \
        --namespace "${CONTEXT_SERVICE_NAMESPACE}" \
        --ignore-not-found
)

echo "Populate dataset-service"
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

    kubectl delete configmap dataset-seed \
        --namespace "${DATASET_SERVICE_NAMESPACE}" \
        --ignore-not-found
)