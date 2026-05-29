package domain

import "testing"

func TestPropertyMaxLevelUsesHighestSatisfiedLevel(t *testing.T) {
	fast, err := NewCondition("cpu", "Gte", []string{"8"})
	if err != nil {
		t.Fatal(err)
	}
	gpu, err := NewCondition("gpu", "Exists", nil)
	if err != nil {
		t.Fatal(err)
	}
	property := Property{Name: "computation", Levels: []Level{
		{Level: 1, Clauses: []Clause{{Conditions: []Condition{fast}}}},
		{Level: 2, Clauses: []Clause{{Conditions: []Condition{fast, gpu}}}},
	}}

	level, err := property.MaxLevel(map[string]string{"cpu": "16", "gpu": "true"})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if level != 2 {
		t.Fatalf("expected level 2, got %d", level)
	}
}

func TestOperatorsPreservePythonSemantics(t *testing.T) {
	value := "gold"
	tests := []struct {
		name     string
		op       string
		node     *string
		values   []string
		expected bool
	}{
		{name: "exists", op: "Exists", node: &value, expected: true},
		{name: "not exists", op: "NotExists", expected: true},
		{name: "eq", op: "Eq", node: &value, values: []string{"gold"}, expected: true},
		{name: "in", op: "In", node: &value, values: []string{"silver", "gold"}, expected: true},
		{name: "not in", op: "NotIn", node: &value, values: []string{"bronze"}, expected: true},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			actual, err := Operators[test.op].Evaluate(test.node, test.values)
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if actual != test.expected {
				t.Fatalf("expected %t, got %t", test.expected, actual)
			}
		})
	}
}
