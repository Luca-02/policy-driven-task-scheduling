package transferscore

import (
	"math"

	"k8s.io/kubernetes/pkg/scheduler/framework"
)

// computePhiTransfer computes the transfer-based phi score for a candidate node based
// on the data locality of the required datasets.
//
// The score is defined as:
//
//	phi_transfer(n,t) = 1 - size(remote(n,t))/size(req(t))
//
// Parameters:
//   - nodeName: name of the candidate node n.
//   - state: pre-computed state for the scheduling cycle, containing the
//
// Returns:
//   - A float64 value representing phi_transfer(n,t), normalized in the range
//     [0, 1]. Higher values indicate a better match between node data locality
//     and task requirements.
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
