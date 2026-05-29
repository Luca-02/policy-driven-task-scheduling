# Node Property Controller file-by-file guide

This document explains what every file in `node-property-controller` does after the Go rewrite.

## Root files

### `go.mod`
Declares the Go module and the Kubernetes-native dependencies used by the controller: `k8s.io/api`, `k8s.io/apimachinery`, `k8s.io/client-go` and `k8s.io/klog/v2`.

### `main.go`
Application entrypoint. It:

- reads runtime configuration from environment variables;
- starts the `/healthz` HTTP endpoint;
- loads in-cluster config first, then falls back to local kubeconfig;
- creates the Kubernetes core client and dynamic client;
- supports `--local` to disable leader election during local development;
- starts native `client-go` Lease-based leader election in cluster mode;
- starts the reconciler only from the elected leader callback.

### `Dockerfile`
Multi-stage container build. The first stage compiles a static Go binary. The final stage uses a distroless non-root image and runs only the compiled controller binary.

### `README.md`
User-facing usage documentation: architecture summary, supported environment variables, local execution, image build, deployment and verification commands.

### `GO_CONTROLLER_DESIGN.md`
Design rationale for the Go implementation: what stayed compatible with Python, which Kubernetes-native mechanisms are used, why informers/workqueues/Lease election are better, and how to extend operators.

### `FILE_GUIDE.md`
This file. It gives a file-by-file overview for maintainers.

## `internal/api/v1alpha1`

### `internal/api/v1alpha1/types.go`
Defines the standard API metadata for the `NodeProperty` CRD in code instead of reading group/version/resource from environment variables. It includes:

- `GroupName`, `Version`, `Resource`, `Kind` constants;
- `SchemeGroupVersion` and `GroupVersionResource` values used by the dynamic informer;
- Go structs that mirror the CRD shape (`NodeProperty`, `NodePropertySpec`, `LevelSpec`, `DisjunctionSpec`, `ConditionSpec`).

The controller currently still watches the CRD through a dynamic informer, but the API constants and structs keep the project aligned with normal Kubernetes Go project layout and make a future generated typed client straightforward.

## `internal/config`

### `internal/config/config.go`
Contains runtime-only configuration. It intentionally does **not** expose CRD `GROUP`, `VERSION` or `PLURAL` as env vars; those belong to the API package. Environment variables here control process behavior only, for example label prefix base names, health address, leader election and worker count.

`ATTRIBUTE_PREFIX` defaults to `attribute.node` and `PROPERTY_PREFIX` defaults to `property.node`. The controller appends the API group (`policydriven.unimi.it`) when building full Kubernetes label prefixes, producing labels such as `attribute.node.policydriven.unimi.it/cpu`.

### `internal/config/config_test.go`
Tests configuration defaults, valid overrides and invalid fallback behavior.

## `internal/domain`

### `internal/domain/operators.go`
Implements condition operators with a simple switch-based function, not a class-like hierarchy. The file defines operator constants and `EvaluateOperator`, including numeric comparisons and error reporting for invalid numeric input.

### `internal/domain/models.go`
Contains the pure scheduling/property model:

- `Condition` is one atomic expression;
- `Clause` is an AND of conditions;
- `Level` is an OR of clauses;
- `Property` returns the highest satisfied level;
- `Node` stores extracted attributes and computed property levels.

This package has no Kubernetes dependencies and can be tested without a cluster.

### `internal/domain/operators_test.go`
Covers the operator truth table for all supported operators and validates numeric/unknown-operator errors.

### `internal/domain/models_test.go`
Covers highest-level selection, implicit level `0`, DNF AND/OR semantics, node property storage and unknown operator validation.

## `internal/controller`

### `internal/controller/parser.go`
Translates Kubernetes object data into the pure domain model:

- extracts input node attributes from labels under the resolved attribute prefix;
- extracts existing computed property labels under the resolved property prefix;
- parses unstructured `NodeProperty` CRD objects into `domain.Property` values;
- converts int-or-string condition values to strings so operator evaluation remains consistent.

### `internal/controller/controller.go`
The native Kubernetes controller implementation. It:

- builds shared informers for `Node` and `NodeProperty` resources;
- waits for informer cache sync before reconciling;
- stores parsed properties in memory, rebuilt from the informer cache on startup;
- queues node/property events through a rate-limited workqueue;
- reconciles nodes by evaluating all known properties from cache;
- reconciles property changes by re-evaluating all cached nodes for that property;
- removes stale property labels when a `NodeProperty` is deleted;
- skips control-plane nodes;
- sends strategic merge patches only when a node label actually needs to change.

### `internal/controller/parser_test.go`
Tests label extraction, property parsing, int-or-string conversion and invalid `NodeProperty` shapes.

## `k8s`

### `k8s/namespace.yaml`
Creates the `node-property-controller` namespace.

### `k8s/rbac.yaml`
Creates the service account, cluster role and binding. Permissions are limited to:

- `get/list/watch/patch` nodes;
- `get/list/watch` `nodeproperties`;
- Lease CRUD operations needed by client-go leader election.

### `k8s/network-policy.yaml`
Restricts ingress to the health endpoint and egress to DNS/API-server ports.

### `k8s/deployment.yaml`
Runs three replicas for HA. Every pod is healthy and participates in leader election, but only the current leader starts active reconciliation and mutates node labels. The manifest uses non-root security context, read-only root filesystem, health probes and resource limits.
