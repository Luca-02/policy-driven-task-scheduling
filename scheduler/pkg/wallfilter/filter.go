package wallfilter

import (
	"context"
	"encoding/json"
	"fmt"

	fwk "k8s.io/kube-scheduler/framework"

	"github.com/Luca-02/policy-driven-task-scheduling/scheduler/internal/contexts"
)

// checkWall decides c_wall for a single candidate node:
//
//	n |=_t c_wall  <=>  (auth(iss(t)) x Lambda(n)) intersect X_conf = empty
//
// Returns Success if c_wall holds; an Unschedulable status if a
// conflict is found; an Error status if the check couldn't be completed
// (context-service unreachable, malformed response, etc.)
func checkWall(ctx context.Context, client contexts.WallChecker, issuer string, lambda []string) *fwk.Status {
	if len(lambda) == 0 {
		// (auth(iss(t)) x {}) intersect X_conf = empty always: no need
		// to call context-service for a node with no recorded traces.
		return fwk.NewStatus(fwk.Success)
	}

	conflicts, err := client.CheckWallConflicts(ctx, issuer, lambda)
	if err != nil {
		return fwk.AsStatus(fmt.Errorf("checking wall conflicts: %w", err))
	}

	if len(conflicts) > 0 {
		return fwk.NewStatus(fwk.Unschedulable,
			fmt.Sprintf("c_wall violated: %d conflicting context pair(s) with node memory", len(conflicts)))
	}

	return fwk.NewStatus(fwk.Success)
}

// parseCtxStar decodes the ctx*(t) annotation value carried by the Pod.
// An empty raw value (annotation absent, or present but empty) is not
// an error: it means ctx*(t) = empty (the task requested only public
// datasets), and returns (nil, nil).
func parseCtxStar(raw string) ([]string, error) {
	if raw == "" {
		return nil, nil
	}

	var ctxStar []string
	if err := json.Unmarshal([]byte(raw), &ctxStar); err != nil {
		return nil, err
	}

	return ctxStar, nil
}
