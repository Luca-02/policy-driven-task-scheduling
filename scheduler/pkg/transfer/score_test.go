package transfer

import "testing"

func TestBuildTransferState(t *testing.T) {
	st := buildTransferState([]DatasetInfo{
		{Name: "d1", SizeMB: 1024, Nodes: []string{"n1", "n4"}},
		{Name: "d2", SizeMB: 2048, Nodes: []string{"n1"}},
	})
	if st.totalSizeMB != 3072 {
		t.Fatalf("total size = %d, want 3072", st.totalSizeMB)
	}
	if len(st.datasets) != 2 {
		t.Fatalf("datasets = %d, want 2", len(st.datasets))
	}
	if _, ok := st.datasets[0].nodes["n4"]; !ok {
		t.Errorf("d1 should be hosted on n4")
	}
	if _, ok := st.datasets[1].nodes["n4"]; ok {
		t.Errorf("d2 should NOT be hosted on n4")
	}
}

func TestComputeTransferScore(t *testing.T) {
	// Esempio ricorrente della tesi: req(t1)={d1,d2}, size(d1)=1024, size(d2)=2048,
	// lambda(d1)={n1,n4}, lambda(d2)={n1}. Attesi: phi(n1)=1 -> 100, phi(n4)=1/3 -> 33.
	thesis := buildTransferState([]DatasetInfo{
		{SizeMB: 1024, Nodes: []string{"n1", "n4"}},
		{SizeMB: 2048, Nodes: []string{"n1"}},
	})

	tests := []struct {
		name  string
		node  string
		state *transferState
		want  int64
	}{
		{"thesis n1: all local", "n1", thesis, 100},
		{"thesis n4: d2 remote", "n4", thesis, 33},
		{
			"all datasets remote", "nX",
			buildTransferState([]DatasetInfo{{SizeMB: 500, Nodes: []string{"other"}}}),
			0,
		},
		{
			"all datasets local", "n1",
			buildTransferState([]DatasetInfo{{SizeMB: 500, Nodes: []string{"n1"}}}),
			100,
		},
		{"empty req(t) -> phi=1", "n1", &transferState{}, 100},
		{
			"zero total volume -> phi=1", "nX",
			buildTransferState([]DatasetInfo{{SizeMB: 0, Nodes: []string{"other"}}}),
			100,
		},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			if got := computeTransferScore(tc.node, tc.state); got != tc.want {
				t.Errorf("score = %d, want %d", got, tc.want)
			}
		})
	}
}
