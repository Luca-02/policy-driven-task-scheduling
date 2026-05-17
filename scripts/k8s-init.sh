#!/bin/bash

# Start cluster with kind
kind create cluster --config k8s/cluster-config.yaml

# Headlamp for dashboard
echo "Installing Headlamp dashboard..."
kubectl apply -f https://raw.githubusercontent.com/kinvolk/headlamp/main/kubernetes-headlamp.yaml
echo

# Create service account and cluster role binding for Headlamp
echo "Creating service account and cluster role binding for Headlamp..."
kubectl -n kube-system create serviceaccount headlamp-admin
kubectl create clusterrolebinding headlamp-admin --serviceaccount=kube-system:headlamp-admin --clusterrole=cluster-admin
echo

# Install the NodePropertyDefinition CRD
echo "Installing NodePropertyDefinition CRD..."
kubectl apply -f node-property/node-property-definitions-crd.yaml
echo

# Install the node properties
echo "Installing node properties..."
kubectl apply -f node-property/security-node-property.yaml
kubectl apply -f node-property/computation-node-property.yaml
echo
