package propscore

import (
	"math"

	"k8s.io/kubernetes/pkg/scheduler/framework"

	"github.com/Luca-02/policy-driven-task-scheduling/scheduler/internal/nodeproperty"
)

// computePhiProp implements phi_prop(n,t) = 1 / (1 + Delta(n,t)) mapped into
// [0, 1], where Delta(n,t) is the weighted normalized property excess:
//
//	Delta(n,t) = sum_{p: beta*_p(t) < maxL_p} w_p * (alpha_p(n) - beta*_p(t)) / (maxL_p - beta*_p(t))
//
// betaStar holds beta*_p(t) for each property p in the task's requirements;
// nodeLevels holds alpha_p(n) for the candidate node, read from its labels
// (an absent label means alpha_p(n) = 0, the implicit default level).
// Properties not found in the NodeProperty registry are skipped: an unknown
// property carries no discriminating information, consistent with how the
// rest of the system tolerates unresolved references.
func computePhiProp(betaStar map[string]int, nodeLevels map[string]int, properties nodeproperty.Reader) float64 {
	delta := 0.0
	for prop, betaP := range betaStar {
		info, found := properties.Get(prop)
		if !found {
			continue
		}
		maxLevel := int(info.MaxLevel)
		if betaP >= maxLevel {
			continue // term excluded: not discriminating (beta*_p == max L_p)
		}
		alphaP := nodeLevels[prop] // absent label => level 0
		numer := float64(alphaP - betaP)
		denom := float64(maxLevel - betaP)
		delta += info.Weight * (numer / denom)
	}
	return 1.0 / (1.0 + delta)
}

// FromPhi maps a normalized indicator phi in [0,1], as formalized in the
// thesis model, into a Kubernetes NodeScore in [0, framework.MaxNodeScore].
func FromPhi(phi float64) int64 {
	return int64(math.Round(phi * float64(framework.MaxNodeScore)))
}
