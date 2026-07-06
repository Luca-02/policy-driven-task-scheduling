package transfer

import (
	"math"

	fwk "k8s.io/kube-scheduler/framework"
	"k8s.io/kubernetes/pkg/scheduler/framework"
)

const stateKey fwk.StateKey = "TransferScore"

// datasetLocality: dataset size and the set of nodes hosting it (lambda(d)).
type datasetLocality struct {
	sizeMB int
	nodes  map[string]struct{}
}

// transferState is the data shared from PreScore to Score. Implements fwk.StateData.
type transferState struct {
	totalSizeMB int               // size(req(t))
	datasets    []datasetLocality // one entry per dataset in req(t)
}

// Clone: the state is read-only after PreScore, so returning itself is safe.
func (s *transferState) Clone() fwk.StateData { return s }

// buildTransferState builds the state from what the dataset-service returns.
func buildTransferState(infos []DatasetInfo) *transferState {
	st := &transferState{}
	for _, info := range infos {
		nodeSet := make(map[string]struct{}, len(info.Nodes))
		for _, n := range info.Nodes {
			nodeSet[n] = struct{}{}
		}
		st.datasets = append(st.datasets, datasetLocality{sizeMB: info.SizeMB, nodes: nodeSet})
		st.totalSizeMB += info.SizeMB
	}
	return st
}

// computeTransferScore implements phi_transfer(n,t) = 1 - size(remote(n,t))/size(req(t))
// mapped into [0, 100]. By model convention, if req(t) is empty (or the total
// volume is zero) there is no transfer and phi_transfer = 1 (max score).
func computeTransferScore(nodeName string, st *transferState) int64 {
	if st.totalSizeMB == 0 {
		return framework.MaxNodeScore
	}
	remoteSizeMB := 0
	for _, d := range st.datasets {
		if _, local := d.nodes[nodeName]; !local {
			remoteSizeMB += d.sizeMB // dataset not on n: must be transferred
		}
	}
	phi := 1.0 - float64(remoteSizeMB)/float64(st.totalSizeMB)
	return int64(math.Round(phi * float64(framework.MaxNodeScore)))
}
