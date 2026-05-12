#!/bin/bash

# Start cluster with kind
kind create cluster --config k8s/cluster-config.yaml

# Headlamp for dashboard
echo "Installing Headlamp dashboard..."
kubectl apply -f https://raw.githubusercontent.com/kinvolk/headlamp/main/kubernetes-headlamp.yaml

# Create service account and cluster role binding for Headlamp
echo "Creating service account and cluster role binding for Headlamp..."
kubectl -n kube-system create serviceaccount headlamp-admin
kubectl create clusterrolebinding headlamp-admin --serviceaccount=kube-system:headlamp-admin --clusterrole=cluster-admin

###

# Install the NodePropertyDefinition CRD
# echo "Installing NodePropertyDefinition CRD..."
# kubectl apply -f k8s/node-property/propertydefinition-crd.yaml

# Install the node properties
# kubectl apply -f k8s/node-property/security-node-property.yaml
# kubectl apply -f k8s/node-property/computation-node-property.yaml

# Check if the CRD and node properties are created successfully
# kubectl get nprdef
# kubectl describe nprdef security
# kubectl describe nprdef computation