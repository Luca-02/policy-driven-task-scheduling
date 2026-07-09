package transferscore

import (
	"math"

	"k8s.io/kubernetes/pkg/scheduler/framework"
)

// computePhiTransfer implements phi_transfer(n,t) = 1 - size(remote(n,t))/size(req(t))
// mapped into [0, 1]. By model convention, if req(t) is empty (or the total
// volume is zero) there is no transfer and phi_transfer = 1 (max score).
func computePhiTransfer(nodeName string, state *preScoreState) float64 {
	if len(state.datasets) == 0 || state.totalSizeMB == 0 {
		return 1.0
	}

	remoteSizeMB := 0
	for _, dataset := range state.datasets {
		if _, local := dataset.nodes[nodeName]; !local {
			remoteSizeMB += dataset.sizeMB // dataset not on n: must be transferred
		}
	}

	return 1.0 - float64(remoteSizeMB)/float64(state.totalSizeMB)
}

// FromPhi maps a normalized indicator phi in [0,1], as formalized in the
// thesis model, into a Kubernetes NodeScore in [0, framework.MaxNodeScore].
func FromPhi(phi float64) int64 {
	return int64(math.Round(phi * float64(framework.MaxNodeScore)))
}
