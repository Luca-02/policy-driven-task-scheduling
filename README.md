# policy-driven-task-scheduling

This repository contains Kubernetes manifests and controllers for policy-driven task scheduling experiments.

## Node Property Controller

The `node-property-controller` component has been rewritten in Go with Kubernetes-native libraries. It watches `NodeProperty` custom resources and Kubernetes `Node` objects, evaluates node attributes, and writes computed property levels as node labels.

Highlights:

- native `client-go` informers and local caches instead of repeated list calls;
- rate-limited reconciliation workqueue;
- `coordination.k8s.io/Lease` leader election for HA deployments;
- deployment configured with three replicas where only the leader patches node labels;
- local execution with `go run main.go --local`.

See [`node-property-controller/README.md`](node-property-controller/README.md) for build, local test and deployment commands, [`node-property-controller/GO_CONTROLLER_DESIGN.md`](node-property-controller/GO_CONTROLLER_DESIGN.md) for design rationale, and [`node-property-controller/FILE_GUIDE.md`](node-property-controller/FILE_GUIDE.md) for a file-by-file explanation.

## Quick local controller commands

```bash
cd node-property-controller
go test ./internal/domain ./internal/config
go run main.go --local
```

## Quick cluster deployment

```bash
kubectl apply -f k8s/crd/node-property-crd.yaml
kubectl apply -f node-property-controller/k8s/namespace.yaml
kubectl apply -f node-property-controller/k8s/rbac.yaml
kubectl apply -f node-property-controller/k8s/network-policy.yaml
kubectl apply -f node-property-controller/k8s/deployment.yaml
```
