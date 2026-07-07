package transferscore

import (
	"testing"

	"github.com/Luca-02/policy-driven-task-scheduling/scheduler/internal/datasets"
)

func TestBuildPreScoreState(t *testing.T) {
	infos := []datasets.DatasetInfo{
		{
			SizeMB: 100,
			Nodes:  []string{"n1", "n2"},
		},
		{
			SizeMB: 200,
			Nodes:  []string{"n2"},
		},
	}

	state := buildPreScoreState(infos)

	if state.totalSizeMB != 300 {
		t.Fatalf("expected totalSizeMB=300, got %d", state.totalSizeMB)
	}

	if len(state.datasets) != 2 {
		t.Fatalf("expected 2 datasets, got %d", len(state.datasets))
	}

	if _, ok := state.datasets[0].nodes["n1"]; !ok {
		t.Errorf("n1 should contain first dataset")
	}

	if _, ok := state.datasets[0].nodes["n2"]; !ok {
		t.Errorf("n2 should contain first dataset")
	}

	if _, ok := state.datasets[1].nodes["n2"]; !ok {
		t.Errorf("n2 should contain second dataset")
	}
}
