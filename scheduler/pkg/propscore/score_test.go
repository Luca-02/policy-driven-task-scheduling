package propscore

import (
	"math"
	"testing"

	"github.com/Luca-02/policy-driven-task-scheduling/scheduler/internal/nodeproperty"
)

type fakeReader map[string]nodeproperty.NodePropertyInfo

func (f fakeReader) Get(name string) (nodeproperty.NodePropertyInfo, bool) {
	info, ok := f[name]
	return info, ok
}

func floatsEqual(a, b float64) bool {
	const epsilon = 1e-9
	return math.Abs(a-b) < epsilon
}

func TestComputePhiPropIdealNode(t *testing.T) {
	// alpha_p(n) == beta*_p(t) for every property: zero excess, phi = 1.
	properties := fakeReader{
		"security": {Name: "security", MaxLevel: 3, Weight: 1},
	}
	betaStar := map[string]int{"security": 2}
	nodePropertiesLevel := map[string]int{"security": 2}

	got := computePhiProp(betaStar, nodePropertiesLevel, properties)
	if !floatsEqual(got, 1.0) {
		t.Errorf("phi_prop = %v, want 1.0", got)
	}
}

func TestComputePhiPropExcessReducesScore(t *testing.T) {
	// alpha_p(n) = maxL_p, beta*_p(t) = 0: maximum possible excess for this property.
	properties := fakeReader{
		"security": {Name: "security", MaxLevel: 4, Weight: 1},
	}
	betaStar := map[string]int{"security": 0}
	nodePropertiesLevel := map[string]int{"security": 4}

	// Delta = 1 * (4-0)/(4-0) = 1 -> phi = 1/(1+1) = 0.5
	got := computePhiProp(betaStar, nodePropertiesLevel, properties)
	if !floatsEqual(got, 0.5) {
		t.Errorf("phi_prop = %v, want 0.5", got)
	}
}

func TestComputePhiPropWeightScalesExcess(t *testing.T) {
	properties := fakeReader{
		"security": {Name: "security", MaxLevel: 2, Weight: 3}, // same excess, tripled weight
	}
	betaStar := map[string]int{"security": 0}
	nodePropertiesLevel := map[string]int{"security": 2}

	// Delta = 3 * (2-0)/(2-0) = 3 -> phi = 1/(1+3) = 0.25
	got := computePhiProp(betaStar, nodePropertiesLevel, properties)
	if !floatsEqual(got, 0.25) {
		t.Errorf("phi_prop = %v, want 0.25", got)
	}
}

func TestComputePhiPropExcludesTermAtMaxLevel(t *testing.T) {
	// beta*_p(t) == maxL_p: term excluded from the sum regardless of alpha_p(n).
	properties := fakeReader{
		"security": {Name: "security", MaxLevel: 2, Weight: 1},
	}
	betaStar := map[string]int{"security": 2}
	nodePropertiesLevel := map[string]int{"security": 2}

	got := computePhiProp(betaStar, nodePropertiesLevel, properties)
	if !floatsEqual(got, 1.0) {
		t.Errorf("phi_prop = %v, want 1.0 (term excluded)", got)
	}
}

func TestComputePhiPropUnknownPropertySkipped(t *testing.T) {
	properties := fakeReader{} // empty registry
	betaStar := map[string]int{"ghost": 1}
	nodePropertiesLevel := map[string]int{"ghost": 3}

	got := computePhiProp(betaStar, nodePropertiesLevel, properties)
	if !floatsEqual(got, 1.0) {
		t.Errorf("phi_prop = %v, want 1.0 (unknown property contributes nothing)", got)
	}
}

func TestComputePhiPropMissingNodeLabelDefaultsToZero(t *testing.T) {
	properties := fakeReader{
		"security": {Name: "security", MaxLevel: 2, Weight: 1},
	}
	betaStar := map[string]int{"security": 0}
	nodePropertiesLevel := map[string]int{} // no label for "security" on this node

	// alpha_p(n) defaults to 0 -> Delta = 1*(0-0)/(2-0) = 0 -> phi = 1
	got := computePhiProp(betaStar, nodePropertiesLevel, properties)
	if !floatsEqual(got, 1.0) {
		t.Errorf("phi_prop = %v, want 1.0", got)
	}
}

func TestComputePhiPropMultipleProperties(t *testing.T) {
	properties := fakeReader{
		"security":    {Name: "security", MaxLevel: 4, Weight: 1},
		"computation": {Name: "computation", MaxLevel: 2, Weight: 2},
	}
	betaStar := map[string]int{"security": 1, "computation": 0}
	nodePropertiesLevel := map[string]int{"security": 2, "computation": 1}

	// security:    1 * (2-1)/(4-1) = 1/3
	// computation: 2 * (1-0)/(2-0) = 1
	// Delta = 1/3 + 1 = 4/3 -> phi = 1/(1+4/3) = 3/7
	got := computePhiProp(betaStar, nodePropertiesLevel, properties)
	want := 3.0 / 7.0
	if !floatsEqual(got, want) {
		t.Errorf("phi_prop = %v, want %v", got, want)
	}
}

func TestComputePhiPropEmptyBetaStar(t *testing.T) {
	got := computePhiProp(nil, map[string]int{"security": 5}, fakeReader{})
	if !floatsEqual(got, 1.0) {
		t.Errorf("phi_prop = %v, want 1.0 (no requirements)", got)
	}
}

func TestFromPhi(t *testing.T) {
	tests := []struct {
		phi  float64
		want int64
	}{
		{1.0, 100},
		{0.0, 0},
		{0.5, 50},
		{1.0 / 3.0, 33},
	}
	for _, tc := range tests {
		if got := FromPhi(tc.phi); got != tc.want {
			t.Errorf("FromPhi(%v) = %d, want %d", tc.phi, got, tc.want)
		}
	}
}
