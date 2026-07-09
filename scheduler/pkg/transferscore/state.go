package transferscore

import (
	"fmt"
	"strings"

	fwk "k8s.io/kube-scheduler/framework"

	"github.com/Luca-02/policy-driven-task-scheduling/scheduler/internal/datasets"
)

type dataset struct {
	sizeMB int
	nodes  map[string]struct{}
}

// preScoreState holds the state of the pre-scoring phase.
type preScoreState struct {
	totalSizeMB int       // size(req(t))
	datasets    []dataset // req(t)
}

func (s *preScoreState) Clone() fwk.StateData {
	return s
}

// buildPreScoreState builds the state from what the dataset-service returns.
func buildPreScoreState(datasetsInfo []datasets.DatasetInfo) *preScoreState {
	state := &preScoreState{}
	for _, info := range datasetsInfo {
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

func (s *preScoreState) String() string {
	var b strings.Builder

	fmt.Fprintf(&b, "preScoreState{totalSizeMB=%d, datasets=[", s.totalSizeMB)

	for i, d := range s.datasets {
		if i > 0 {
			b.WriteString(", ")
		}

		nodes := make([]string, 0, len(d.nodes))
		for n := range d.nodes {
			nodes = append(nodes, n)
		}

		fmt.Fprintf(&b, "{sizeMB=%d, nodes=%v}", d.sizeMB, nodes)
	}

	b.WriteString("]}")
	return b.String()
}
