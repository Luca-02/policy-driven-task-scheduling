#!/bin/sh

TOKEN=$(kubectl create token headlamp-admin -n kube-system)
echo "Use the following token to log in to the Headlamp dashboard:"
echo $TOKEN
echo 
echo "Starting port forwarding to access the dashboard at http://localhost:8080"
kubectl port-forward -n kube-system service/headlamp 8080:80