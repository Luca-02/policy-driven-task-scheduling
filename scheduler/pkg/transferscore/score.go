package transferscore

import (
	"math"

	fwk "k8s.io/kube-scheduler/framework"
	"k8s.io/kubernetes/pkg/scheduler/framework"

	"github.com/Luca-02/policy-driven-task-scheduling/scheduler/internal/datasets"
)

const transferStateKey fwk.StateKey = "transferState"

type dataset struct {
	sizeMB int
	nodes  map[string]struct{}
}

type transferState struct {
	totalSizeMB int       // size(req(t))
	datasets    []dataset // req(t)
}

func (s *transferState) Clone() fwk.StateData {
	return s
}

// buildTransferState builds the state from what the dataset-service returns.
func buildTransferState(infos []datasets.DatasetInfo) *transferState {
	state := &transferState{}
	for _, info := range infos {
		nodeSet := make(map[string]struct{}, len(info.Nodes))
		for _, n := range info.Nodes {
			nodeSet[n] = struct{}{}
		}
		dataset := dataset{sizeMB: info.SizeMB, nodes: nodeSet}
		state.datasets = append(state.datasets, dataset)
		state.totalSizeMB += info.SizeMB
	}
	return state
}

// computeTransferPhi implements phi_transfer(n,t) = 1 - size(remote(n,t))/size(req(t))
// mapped into [0, 1]. By model convention, if req(t) is empty (or the total
// volume is zero) there is no transfer and phi_transfer = 1 (max score).
func computeTransferPhi(nodeName string, st *transferState) float64 {
	if len(st.datasets) == 0 || st.totalSizeMB == 0 {
		return 1.0
	}

	remoteSizeMB := 0
	for _, dataset := range st.datasets {
		if _, local := dataset.nodes[nodeName]; !local {
			remoteSizeMB += dataset.sizeMB // dataset not on n: must be transferred
		}
	}

	return 1.0 - float64(remoteSizeMB)/float64(st.totalSizeMB)
}

// FromPhi maps a normalized indicator phi in [0,1], as formalized in the
// thesis model, into a Kubernetes NodeScore in [0, framework.MaxNodeScore].
func FromPhi(phi float64) int64 {
	return int64(math.Round(phi * float64(framework.MaxNodeScore)))
}
