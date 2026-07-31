package contexts

import (
	"context"
	"net/http"
)

// Conflict is a single pair of contexts found to be in X_conf.
type Conflict struct {
	ContextA string `json:"context_a"`
	ContextB string `json:"context_b"`
}

// WallCheckRequest holds the request body sent to context-service when checking
// c_wall for a candidate node: Lambda(n), the set of contexts already deposited
// on that node.
type WallCheckRequest struct {
	Contexts []string `json:"contexts"`
}

// WallCheckResponse holds the response body from context-service's wall-check
// endpoint. An empty Conflicts slice means c_wall is satisfied:
//
//	(auth(iss(t)) x Lambda(n)) intersect X_conf = empty
type WallCheckResponse struct {
	Conflicts []Conflict `json:"conflicts"`
}

// ContextClient is a client for context-service.
type ContextClient struct {
	baseURL string
	http    *http.Client
}

// WallChecker acts as a client for context-service's c_wall check.
type WallChecker interface {
	CheckWallConflicts(ctx context.Context, issuer string, lambda []string) ([]Conflict, error)
}
