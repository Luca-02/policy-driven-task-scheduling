package domain

import (
	"strings"
	"testing"
)

func TestEvaluateOperatorTruthTable(t *testing.T) {
	gold := "gold"
	five := "5"
	tests := []struct {
		name     string
		op       string
		node     *string
		values   []string
		expected bool
	}{
		{name: "exists true", op: OperatorExists, node: &gold, expected: true},
		{name: "exists false", op: OperatorExists, expected: false},
		{name: "not exists true", op: OperatorNotExists, expected: true},
		{name: "not exists false", op: OperatorNotExists, node: &gold, expected: false},
		{name: "eq true", op: OperatorEq, node: &gold, values: []string{"gold"}, expected: true},
		{name: "eq false value", op: OperatorEq, node: &gold, values: []string{"silver"}, expected: false},
		{name: "eq false missing", op: OperatorEq, values: []string{"gold"}, expected: false},
		{name: "not eq true", op: OperatorNotEq, node: &gold, values: []string{"silver"}, expected: true},
		{name: "not eq false equal", op: OperatorNotEq, node: &gold, values: []string{"gold"}, expected: false},
		{name: "not eq false missing", op: OperatorNotEq, values: []string{"gold"}, expected: false},
		{name: "in true", op: OperatorIn, node: &gold, values: []string{"silver", "gold"}, expected: true},
		{name: "in false", op: OperatorIn, node: &gold, values: []string{"bronze"}, expected: false},
		{name: "in false missing", op: OperatorIn, values: []string{"gold"}, expected: false},
		{name: "not in true", op: OperatorNotIn, node: &gold, values: []string{"bronze"}, expected: true},
		{name: "not in false", op: OperatorNotIn, node: &gold, values: []string{"bronze", "gold"}, expected: false},
		{name: "not in false missing", op: OperatorNotIn, values: []string{"gold"}, expected: false},
		{name: "gt true", op: OperatorGt, node: &five, values: []string{"4"}, expected: true},
		{name: "gt false", op: OperatorGt, node: &five, values: []string{"5"}, expected: false},
		{name: "lt true", op: OperatorLt, node: &five, values: []string{"6"}, expected: true},
		{name: "lt false", op: OperatorLt, node: &five, values: []string{"5"}, expected: false},
		{name: "gte true equal", op: OperatorGte, node: &five, values: []string{"5"}, expected: true},
		{name: "gte false", op: OperatorGte, node: &five, values: []string{"6"}, expected: false},
		{name: "lte true equal", op: OperatorLte, node: &five, values: []string{"5"}, expected: true},
		{name: "lte false", op: OperatorLte, node: &five, values: []string{"4"}, expected: false},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			actual, err := EvaluateOperator(test.op, test.node, test.values)
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if actual != test.expected {
				t.Fatalf("expected %t, got %t", test.expected, actual)
			}
		})
	}
}

func TestEvaluateOperatorErrors(t *testing.T) {
	notNumber := "fast"
	if _, err := EvaluateOperator(OperatorGt, &notNumber, []string{"4"}); err == nil || !strings.Contains(err.Error(), "numeric node value") {
		t.Fatalf("expected numeric node value error, got %v", err)
	}
	five := "5"
	if _, err := EvaluateOperator(OperatorGt, &five, []string{"fast"}); err == nil || !strings.Contains(err.Error(), "numeric comparison value") {
		t.Fatalf("expected numeric comparison value error, got %v", err)
	}
	if _, err := EvaluateOperator("Between", &five, []string{"1", "10"}); err == nil || !strings.Contains(err.Error(), "unknown operator") {
		t.Fatalf("expected unknown operator error, got %v", err)
	}
}
