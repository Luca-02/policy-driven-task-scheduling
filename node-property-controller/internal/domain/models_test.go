package domain

import "testing"

func TestPropertyMaxLevelUsesHighestSatisfiedLevel(t *testing.T) {
	cpuAtLeast8 := mustCondition(t, "cpu", OperatorGte, []string{"8"})
	gpuExists := mustCondition(t, "gpu", OperatorExists, nil)
	zoneGold := mustCondition(t, "zone", OperatorEq, []string{"gold"})
	property := Property{Name: "computation", Levels: []Level{
		{Level: 1, Clauses: []Clause{{Conditions: []Condition{cpuAtLeast8}}}},
		{Level: 2, Clauses: []Clause{{Conditions: []Condition{cpuAtLeast8, gpuExists}}}},
		{Level: 3, Clauses: []Clause{{Conditions: []Condition{zoneGold}}}},
	}}

	level, err := property.MaxLevel(map[string]string{"cpu": "16", "gpu": "true", "zone": "gold"})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if level != 3 {
		t.Fatalf("expected level 3, got %d", level)
	}
}

func TestPropertyMaxLevelReturnsZeroWhenNothingMatches(t *testing.T) {
	property := Property{Name: "security", Levels: []Level{
		{Level: 1, Clauses: []Clause{{Conditions: []Condition{mustCondition(t, "tee", OperatorExists, nil)}}}},
	}}
	level, err := property.MaxLevel(map[string]string{"cpu": "16"})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if level != 0 {
		t.Fatalf("expected implicit level 0, got %d", level)
	}
}

func TestDisjunctionAndConjunctionSemantics(t *testing.T) {
	property := Property{Name: "placement", Levels: []Level{
		{Level: 1, Clauses: []Clause{
			{Conditions: []Condition{
				mustCondition(t, "cpu", OperatorGte, []string{"32"}),
				mustCondition(t, "gpu", OperatorExists, nil),
			}},
			{Conditions: []Condition{
				mustCondition(t, "zone", OperatorIn, []string{"gold", "silver"}),
			}},
		}},
	}}

	level, err := property.MaxLevel(map[string]string{"cpu": "8", "zone": "silver"})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if level != 1 {
		t.Fatalf("expected second OR clause to satisfy level 1, got %d", level)
	}

	level, err = property.MaxLevel(map[string]string{"cpu": "32"})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if level != 0 {
		t.Fatalf("expected failed AND clause to leave level 0, got %d", level)
	}
}

func TestNodeEvaluatePropertyStoresComputedLevel(t *testing.T) {
	node := Node{Name: "worker", Attributes: map[string]string{"cpu": "16"}}
	property := Property{Name: "computation", Levels: []Level{
		{Level: 1, Clauses: []Clause{{Conditions: []Condition{mustCondition(t, "cpu", OperatorGte, []string{"8"})}}}},
	}}

	level, err := node.EvaluateProperty(property)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if level != 1 || node.Properties["computation"] != 1 {
		t.Fatalf("expected stored level 1, got level=%d properties=%#v", level, node.Properties)
	}
}

func TestNewConditionRejectsUnknownOperator(t *testing.T) {
	if _, err := NewCondition("cpu", "Between", []string{"1", "8"}); err == nil {
		t.Fatal("expected unknown operator error")
	}
}

func mustCondition(t *testing.T, key, operator string, values []string) Condition {
	t.Helper()
	condition, err := NewCondition(key, operator, values)
	if err != nil {
		t.Fatal(err)
	}
	return condition
}
