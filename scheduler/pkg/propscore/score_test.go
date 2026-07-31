package propscore

import (
	"math"
	"testing"

	"github.com/Luca-02/policy-driven-task-scheduling/scheduler/internal/nodeproperties"
)

type fakeReader map[string]nodeproperties.NodePropertyInfo

func (f fakeReader) Get(name string) (nodeproperties.NodePropertyInfo, bool) {
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
	// alpha_p(n) = maxL_p, beta*_p(t) = 0: maximum possible excess for this
	// property, saturating Delta at Delta_max.
	properties := fakeReader{
		"security": {Name: "security", MaxLevel: 4, Weight: 1},
	}
	betaStar := map[string]int{"security": 0}
	nodePropertiesLevel := map[string]int{"security": 4}

	// Delta = 1 * (4-0)/(4-0) = 1, Delta_max = 1 -> phi = 1 - 1/1 = 0
	got := computePhiProp(betaStar, nodePropertiesLevel, properties)
	want := 0.0
	if !floatsEqual(got, want) {
		t.Errorf("phi_prop = %v, want %v", got, want)
	}
}

func TestComputePhiPropWeightScalesExcess(t *testing.T) {
	// Two properties with different weights and partial excess: the more
	// heavily weighted property dominates the resulting score.
	properties := fakeReader{
		"security":    {Name: "security", MaxLevel: 3, Weight: 3},
		"computation": {Name: "computation", MaxLevel: 3, Weight: 1},
	}
	betaStar := map[string]int{"security": 1, "computation": 1}
	nodePropertiesLevel := map[string]int{"security": 2, "computation": 3}

	// security: 3 * (2-1)/(3-1) = 1.5
	// computation: 1 * (3-1)/(3-1) = 1
	// Delta = 1.5 + 1 = 2.5, Delta_max = 3 + 1 = 4 -> phi = 1 - 2.5/4 = 0.375
	got := computePhiProp(betaStar, nodePropertiesLevel, properties)
	want := 0.375
	if !floatsEqual(got, want) {
		t.Errorf("phi_prop = %v, want %v", got, want)
	}
}

func TestComputePhiPropExcludesTermAtMaxLevel(t *testing.T) {
	// beta*_p(t) == maxL_p: term excluded from both Delta and Delta_max,
	// regardless of alpha_p(n). No discriminating property remains, so the
	// node is trivially ideal.
	properties := fakeReader{
		"security": {Name: "security", MaxLevel: 2, Weight: 1},
	}
	betaStar := map[string]int{"security": 2}
	nodePropertiesLevel := map[string]int{"security": 2}

	got := computePhiProp(betaStar, nodePropertiesLevel, properties)
	want := 1.0
	if !floatsEqual(got, want) {
		t.Errorf("phi_prop = %v, want %v (term excluded)", got, want)
	}
}

func TestComputePhiPropUnknownPropertySkipped(t *testing.T) {
	properties := fakeReader{} // empty registry
	betaStar := map[string]int{"ghost": 1}
	nodePropertiesLevel := map[string]int{"ghost": 3}

	got := computePhiProp(betaStar, nodePropertiesLevel, properties)
	want := 1.0
	if !floatsEqual(got, want) {
		t.Errorf("phi_prop = %v, want %v (unknown property contributes nothing)", got, want)
	}
}

func TestComputePhiPropMissingNodeLabelDefaultsToZero(t *testing.T) {
	properties := fakeReader{
		"security": {Name: "security", MaxLevel: 2, Weight: 1},
	}
	betaStar := map[string]int{"security": 0}
	nodePropertiesLevel := map[string]int{} // no label for "security" on this node

	// alpha_p(n) defaults to 0 -> Delta = 1*(0-0)/(2-0) = 0, Delta_max = 1 -> phi = 1
	got := computePhiProp(betaStar, nodePropertiesLevel, properties)
	want := 1.0
	if !floatsEqual(got, want) {
		t.Errorf("phi_prop = %v, want %v", got, want)
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
	// Delta = 1/3 + 1 = 4/3, Delta_max = 1 + 2 = 3 -> phi = 1 - (4/3)/3 = 5/9
	got := computePhiProp(betaStar, nodePropertiesLevel, properties)
	want := 5.0 / 9.0
	if !floatsEqual(got, want) {
		t.Errorf("phi_prop = %v, want %v", got, want)
	}
}

func TestComputePhiPropEmptyBetaStar(t *testing.T) {
	// No requirements at all: Delta_max = 0, node is trivially ideal.
	got := computePhiProp(nil, map[string]int{"security": 5}, fakeReader{})
	want := 1.0
	if !floatsEqual(got, want) {
		t.Errorf("phi_prop = %v, want %v (no requirements)", got, want)
	}
}

func TestComputePhiPropAllPropertiesAtMaxLevel(t *testing.T) {
	// Every requested property is already at its max level: Delta_max = 0,
	// node is trivially ideal even though it offers no room for excess.
	properties := fakeReader{
		"security":    {Name: "security", MaxLevel: 3, Weight: 1},
		"computation": {Name: "computation", MaxLevel: 2, Weight: 5},
	}
	betaStar := map[string]int{"security": 3, "computation": 2}
	nodePropertiesLevel := map[string]int{"security": 3, "computation": 2}

	got := computePhiProp(betaStar, nodePropertiesLevel, properties)
	want := 1.0
	if !floatsEqual(got, want) {
		t.Errorf("phi_prop = %v, want %v (Delta_max = 0)", got, want)
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
