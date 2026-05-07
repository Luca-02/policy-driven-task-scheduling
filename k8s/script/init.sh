#!/bin/sh

# Start cluster with kind
kind create cluster --config cluster-config.yaml

# Headlamp for dashboard
echo "Installing Headlamp dashboard..."
kubectl apply -f https://raw.githubusercontent.com/kinvolk/headlamp/main/kubernetes-headlamp.yaml

# Create service account and cluster role binding for Headlamp
echo "Creating service account and cluster role binding for Headlamp..."
kubectl -n kube-system create serviceaccount headlamp-admin
kubectl create clusterrolebinding headlamp-admin --serviceaccount=kube-system:headlamp-admin --clusterrole=cluster-admin
