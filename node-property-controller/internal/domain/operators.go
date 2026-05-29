package domain

import (
	"fmt"
	"strconv"
)

const (
	OperatorExists    = "Exists"
	OperatorNotExists = "NotExists"
	OperatorEq        = "Eq"
	OperatorNotEq     = "NotEq"
	OperatorIn        = "In"
	OperatorNotIn     = "NotIn"
	OperatorGt        = "Gt"
	OperatorLt        = "Lt"
	OperatorGte       = "Gte"
	OperatorLte       = "Lte"
)

var KnownOperators = map[string]struct{}{
	OperatorExists:    {},
	OperatorNotExists: {},
	OperatorEq:        {},
	OperatorNotEq:     {},
	OperatorIn:        {},
	OperatorNotIn:     {},
	OperatorGt:        {},
	OperatorLt:        {},
	OperatorGte:       {},
	OperatorLte:       {},
}

func IsKnownOperator(operator string) bool {
	_, ok := KnownOperators[operator]
	return ok
}

func EvaluateOperator(operator string, nodeValue *string, values []string) (bool, error) {
	switch operator {
	case OperatorExists:
		return nodeValue != nil, nil
	case OperatorNotExists:
		return nodeValue == nil, nil
	case OperatorEq:
		return nodeValue != nil && len(values) > 0 && *nodeValue == values[0], nil
	case OperatorNotEq:
		return nodeValue != nil && len(values) > 0 && *nodeValue != values[0], nil
	case OperatorIn:
		return nodeValue != nil && contains(values, *nodeValue), nil
	case OperatorNotIn:
		return nodeValue != nil && !contains(values, *nodeValue), nil
	case OperatorGt, OperatorLt, OperatorGte, OperatorLte:
		return evaluateNumericOperator(operator, nodeValue, values)
	default:
		return false, fmt.Errorf("unknown operator %q", operator)
	}
}

func evaluateNumericOperator(operator string, nodeValue *string, values []string) (bool, error) {
	if nodeValue == nil || len(values) == 0 {
		return false, nil
	}
	left, err := strconv.Atoi(*nodeValue)
	if err != nil {
		return false, fmt.Errorf("operator %s requires numeric node value %q: %w", operator, *nodeValue, err)
	}
	right, err := strconv.Atoi(values[0])
	if err != nil {
		return false, fmt.Errorf("operator %s requires numeric comparison value %q: %w", operator, values[0], err)
	}

	switch operator {
	case OperatorGt:
		return left > right, nil
	case OperatorLt:
		return left < right, nil
	case OperatorGte:
		return left >= right, nil
	case OperatorLte:
		return left <= right, nil
	default:
		return false, fmt.Errorf("unknown numeric operator %q", operator)
	}
}

func contains(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}
