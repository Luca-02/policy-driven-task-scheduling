package domain

import "fmt"

type Condition struct {
	Key      string
	Operator string
	Values   []string
}

func NewCondition(key, operator string, values []string) (Condition, error) {
	if !IsKnownOperator(operator) {
		return Condition{}, fmt.Errorf("unknown operator %q", operator)
	}
	return Condition{Key: key, Operator: operator, Values: values}, nil
}

func (c Condition) Evaluate(attributes map[string]string) (bool, error) {
	value, ok := attributes[c.Key]
	if !ok {
		return EvaluateOperator(c.Operator, nil, c.Values)
	}
	return EvaluateOperator(c.Operator, &value, c.Values)
}

type Clause struct {
	Conditions []Condition
}

func (c Clause) Evaluate(attributes map[string]string) (bool, error) {
	for _, condition := range c.Conditions {
		ok, err := condition.Evaluate(attributes)
		if err != nil || !ok {
			return ok, err
		}
	}
	return true, nil
}

type Level struct {
	Level   int
	Clauses []Clause
}

func (l Level) Evaluate(attributes map[string]string) (bool, error) {
	for _, clause := range l.Clauses {
		ok, err := clause.Evaluate(attributes)
		if err != nil {
			return false, err
		}
		if ok {
			return true, nil
		}
	}
	return false, nil
}

type Property struct {
	Name   string
	Levels []Level
}

func (p Property) MaxLevel(attributes map[string]string) (int, error) {
	maxLevel := 0
	for _, level := range p.Levels {
		ok, err := level.Evaluate(attributes)
		if err != nil {
			return 0, err
		}
		if ok && level.Level > maxLevel {
			maxLevel = level.Level
		}
	}
	return maxLevel, nil
}

type Node struct {
	Name       string
	Attributes map[string]string
	Properties map[string]int
}

func (n *Node) EvaluateProperty(prop Property) (int, error) {
	level, err := prop.MaxLevel(n.Attributes)
	if err != nil {
		return 0, err
	}
	if n.Properties == nil {
		n.Properties = map[string]int{}
	}
	n.Properties[prop.Name] = level
	return level, nil
}
