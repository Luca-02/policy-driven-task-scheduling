package propscore

import (
	"math"

	"k8s.io/kubernetes/pkg/scheduler/framework"

	"github.com/Luca-02/policy-driven-task-scheduling/scheduler/internal/nodeproperty"
)

// computePhiProp computes the property-based phi score for a candidate node.
//
// The score is defined as:
//
//	phi_prop(n,t) = 1 / (1 + Delta(n,t))
//
// where Delta(n,t) is the weighted normalized excess of the node properties
// compared to the task requirements:
//
//	Delta(n,t) = sum_{p: beta*_p(t) < maxL_p} w_p * (alpha_p(n) - beta*_p(t)) / (maxL_p - beta*_p(t))
//
// Properties with beta*_p equal to their
// maximum level are ignored because they do not provide discrimination.
//
// Unknown properties (not present in the NodeProperty registry) are skipped.
//
// Parameters:
//   - betaStar: map of required property levels for the task, where the key is
//     the property name and the value is beta*_p(t), the minimum required level.
//   - nodeLevels: map of property levels for the candidate node, where the key is
//     the property name and the value is alpha_p(n). Missing properties are
//     treated as having level 0.
//   - properties: reader used to retrieve metadata for each property, including
//     its maximum level (maxL_p) and weight (w_p). Properties not found in the
//     registry are ignored.
//
// Returns:
//   - A float64 value representing phi_prop(n,t), normalized in the range
//     [0, 1]. Higher values indicate a better match between node properties
//     and task requirements.
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
		excess := float64(alphaP - betaP)
		norm := float64(maxLevel - betaP)
		delta += info.Weight * (excess / norm)
	}
	return 1.0 / (1.0 + delta)
}

// FromPhi maps a normalized indicator phi in [0,1], as formalized in the
// thesis model, into a Kubernetes NodeScore in [0, framework.MaxNodeScore].
func FromPhi(phi float64) int64 {
	return int64(math.Round(phi * float64(framework.MaxNodeScore)))
}
