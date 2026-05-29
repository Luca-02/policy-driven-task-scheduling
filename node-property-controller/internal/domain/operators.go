package domain

import (
	"fmt"
	"strconv"
)

type Operator interface {
	Name() string
	Evaluate(nodeValue *string, values []string) (bool, error)
}

type OperatorFunc struct {
	name string
	fn   func(nodeValue *string, values []string) (bool, error)
}

func (o OperatorFunc) Name() string { return o.name }
func (o OperatorFunc) Evaluate(nodeValue *string, values []string) (bool, error) {
	return o.fn(nodeValue, values)
}

var Operators = map[string]Operator{
	"Exists":    OperatorFunc{"Exists", func(nodeValue *string, _ []string) (bool, error) { return nodeValue != nil, nil }},
	"NotExists": OperatorFunc{"NotExists", func(nodeValue *string, _ []string) (bool, error) { return nodeValue == nil, nil }},
	"Eq": OperatorFunc{"Eq", func(nodeValue *string, values []string) (bool, error) {
		return nodeValue != nil && len(values) > 0 && *nodeValue == values[0], nil
	}},
	"NotEq": OperatorFunc{"NotEq", func(nodeValue *string, values []string) (bool, error) {
		return nodeValue != nil && len(values) > 0 && *nodeValue != values[0], nil
	}},
	"In": OperatorFunc{"In", func(nodeValue *string, values []string) (bool, error) {
		if nodeValue == nil {
			return false, nil
		}
		for _, value := range values {
			if *nodeValue == value {
				return true, nil
			}
		}
		return false, nil
	}},
	"NotIn": OperatorFunc{"NotIn", func(nodeValue *string, values []string) (bool, error) {
		if nodeValue == nil {
			return false, nil
		}
		for _, value := range values {
			if *nodeValue == value {
				return false, nil
			}
		}
		return true, nil
	}},
	"Gt":  numericOperator("Gt", func(left, right int) bool { return left > right }),
	"Lt":  numericOperator("Lt", func(left, right int) bool { return left < right }),
	"Gte": numericOperator("Gte", func(left, right int) bool { return left >= right }),
	"Lte": numericOperator("Lte", func(left, right int) bool { return left <= right }),
}

func numericOperator(name string, compare func(left, right int) bool) Operator {
	return OperatorFunc{name: name, fn: func(nodeValue *string, values []string) (bool, error) {
		if nodeValue == nil || len(values) == 0 {
			return false, nil
		}
		left, err := strconv.Atoi(*nodeValue)
		if err != nil {
			return false, fmt.Errorf("operator %s requires numeric node value %q: %w", name, *nodeValue, err)
		}
		right, err := strconv.Atoi(values[0])
		if err != nil {
			return false, fmt.Errorf("operator %s requires numeric comparison value %q: %w", name, values[0], err)
		}
		return compare(left, right), nil
	}}
}
