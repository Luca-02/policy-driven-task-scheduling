package transferscore

import (
	"math"
	"testing"

	"k8s.io/kubernetes/pkg/scheduler/framework"
)

const eps = 1e-9

func TestComputePhiTransfer(t *testing.T) {
	tests := []struct {
		name     string
		node     string
		state    *preScoreState
		expected float64
	}{
		{
			name:     "no datasets",
			node:     "n1",
			state:    &preScoreState{},
			expected: 1.0,
		},
		{
			name: "total size zero",
			node: "n1",
			state: &preScoreState{
				totalSizeMB: 0,
				datasets: []dataset{
					{
						sizeMB: 0,
						nodes: map[string]struct{}{
							"n1": {},
						},
					},
				},
			},
			expected: 1.0,
		},
		{
			name: "all datasets local",
			node: "n1",
			state: &preScoreState{
				totalSizeMB: 300,
				datasets: []dataset{
					{
						sizeMB: 100,
						nodes: map[string]struct{}{
							"n1": {},
						},
					},
					{
						sizeMB: 200,
						nodes: map[string]struct{}{
							"n1": {},
						},
					},
				},
			},
			expected: 1.0,
		},
		{
			name: "all datasets remote",
			node: "n1",
			state: &preScoreState{
				totalSizeMB: 300,
				datasets: []dataset{
					{
						sizeMB: 100,
						nodes: map[string]struct{}{
							"n2": {},
						},
					},
					{
						sizeMB: 200,
						nodes: map[string]struct{}{
							"n3": {},
						},
					},
				},
			},
			expected: 0.0,
		},
		{
			name: "half local half remote",
			node: "n1",
			state: &preScoreState{
				totalSizeMB: 300,
				datasets: []dataset{
					{
						sizeMB: 100,
						nodes: map[string]struct{}{
							"n1": {},
						},
					},
					{
						sizeMB: 200,
						nodes: map[string]struct{}{
							"n2": {},
						},
					},
				},
			},
			expected: 1.0 - 200.0/300.0,
		},
		{
			name: "rounding",
			node: "n1",
			state: &preScoreState{
				totalSizeMB: 200,
				datasets: []dataset{
					{
						sizeMB: 99,
						nodes: map[string]struct{}{
							"n1": {},
						},
					},
					{
						sizeMB: 101,
						nodes: map[string]struct{}{
							"n2": {},
						},
					},
				},
			},
			expected: 1.0 - 101.0/200.0,
		},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			got := computePhiTransfer(test.node, test.state)
			if math.Abs(got-test.expected) > eps {
				t.Errorf("result = %f, want %f", got, test.expected)
			}
		})
	}
}

func TestFromPhi(t *testing.T) {
	tests := []struct {
		name     string
		phi      float64
		expected int64
	}{
		{
			name:     "phi=0",
			phi:      0.0,
			expected: 0,
		},
		{
			name:     "phi=0.5",
			phi:      0.5,
			expected: framework.MaxNodeScore / 2,
		},
		{
			name:     "phi=1",
			phi:      1.0,
			expected: framework.MaxNodeScore,
		},
		{
			name:     "phi=0.12345",
			phi:      0.12345,
			expected: int64(math.Round(0.12345 * float64(framework.MaxNodeScore))),
		},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			got := FromPhi(test.phi)
			if got != test.expected {
				t.Errorf("FromPhi(%f) = %d, want %d", test.phi, got, test.expected)
			}
		})
	}
}
