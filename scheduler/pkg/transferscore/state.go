package transferscore

import (
	fwk "k8s.io/kube-scheduler/framework"

	"github.com/Luca-02/policy-driven-task-scheduling/scheduler/internal/datasets"
)

type preScoreState struct {
	totalSizeMB int       // size(req(t))
	datasets    []dataset // req(t)
}

func (s *preScoreState) Clone() fwk.StateData {
	return s
}

// buildPreScoreState builds the state from what the dataset-service returns.
func buildPreScoreState(infos []datasets.DatasetInfo) *preScoreState {
	state := &preScoreState{}
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
