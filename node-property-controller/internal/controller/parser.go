package controller

import (
	"fmt"
	"strconv"
	"strings"

	"github.com/policy-driven-task-scheduling/node-property-controller/internal/config"
	"github.com/policy-driven-task-scheduling/node-property-controller/internal/domain"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
)

func ExtractNodeAttributes(labels map[string]string, cfg config.Config) map[string]string {
	return extractLabels(labels, cfg.AttributePrefix)
}

func ExtractNodeProperties(labels map[string]string, cfg config.Config) map[string]int {
	prefix := cfg.PropertyPrefix + "/"
	properties := map[string]int{}
	for key, value := range labels {
		if strings.HasPrefix(key, prefix) {
			level, err := strconv.Atoi(value)
			if err == nil {
				properties[strings.TrimPrefix(key, prefix)] = level
			}
		}
	}
	return properties
}

func ParseNode(name string, labels map[string]string, cfg config.Config) domain.Node {
	return domain.Node{
		Name:       name,
		Attributes: ExtractNodeAttributes(labels, cfg),
		Properties: ExtractNodeProperties(labels, cfg),
	}
}

func ParseProperty(name string, obj *unstructured.Unstructured) (domain.Property, error) {
	levelsValue, found, err := unstructured.NestedSlice(obj.Object, "spec", "levels")
	if err != nil {
		return domain.Property{}, fmt.Errorf("spec.levels must be a list: %w", err)
	}
	if !found {
		return domain.Property{}, fmt.Errorf("spec.levels is required")
	}

	levels := make([]domain.Level, 0, len(levelsValue))
	for i, rawLevel := range levelsValue {
		levelMap, ok := rawLevel.(map[string]interface{})
		if !ok {
			return domain.Property{}, fmt.Errorf("spec.levels[%d] must be an object", i)
		}
		levelNumber, err := intField(levelMap, "level")
		if err != nil {
			return domain.Property{}, fmt.Errorf("spec.levels[%d].level: %w", i, err)
		}
		rawDisjunction, ok := levelMap["disjunction"].([]interface{})
		if !ok {
			return domain.Property{}, fmt.Errorf("spec.levels[%d].disjunction must be a list", i)
		}

		clauses := make([]domain.Clause, 0, len(rawDisjunction))
		for j, rawClause := range rawDisjunction {
			clauseMap, ok := rawClause.(map[string]interface{})
			if !ok {
				return domain.Property{}, fmt.Errorf("spec.levels[%d].disjunction[%d] must be an object", i, j)
			}
			rawConditions, ok := clauseMap["clause"].([]interface{})
			if !ok {
				return domain.Property{}, fmt.Errorf("spec.levels[%d].disjunction[%d].clause must be a list", i, j)
			}
			conditions := make([]domain.Condition, 0, len(rawConditions))
			for k, rawCondition := range rawConditions {
				conditionMap, ok := rawCondition.(map[string]interface{})
				if !ok {
					return domain.Property{}, fmt.Errorf("spec.levels[%d].disjunction[%d].clause[%d] must be an object", i, j, k)
				}
				key, err := stringField(conditionMap, "key")
				if err != nil {
					return domain.Property{}, err
				}
				operator, err := stringField(conditionMap, "operator")
				if err != nil {
					return domain.Property{}, err
				}
				values := stringSliceField(conditionMap, "values")
				condition, err := domain.NewCondition(key, operator, values)
				if err != nil {
					return domain.Property{}, err
				}
				conditions = append(conditions, condition)
			}
			clauses = append(clauses, domain.Clause{Conditions: conditions})
		}
		levels = append(levels, domain.Level{Level: levelNumber, Clauses: clauses})
	}
	return domain.Property{Name: name, Levels: levels}, nil
}

func extractLabels(labels map[string]string, prefix string) map[string]string {
	prefixWithSlash := prefix + "/"
	result := map[string]string{}
	for key, value := range labels {
		if strings.HasPrefix(key, prefixWithSlash) {
			result[strings.TrimPrefix(key, prefixWithSlash)] = value
		}
	}
	return result
}

func intField(data map[string]interface{}, key string) (int, error) {
	value, ok := data[key]
	if !ok {
		return 0, fmt.Errorf("field %q is required", key)
	}
	switch typed := value.(type) {
	case int64:
		return int(typed), nil
	case int:
		return typed, nil
	case float64:
		return int(typed), nil
	default:
		return 0, fmt.Errorf("field %q must be an integer", key)
	}
}

func stringField(data map[string]interface{}, key string) (string, error) {
	value, ok := data[key]
	if !ok {
		return "", fmt.Errorf("field %q is required", key)
	}
	str, ok := value.(string)
	if !ok {
		return "", fmt.Errorf("field %q must be a string", key)
	}
	return str, nil
}

func stringSliceField(data map[string]interface{}, key string) []string {
	value, ok := data[key]
	if !ok || value == nil {
		return nil
	}
	rawValues, ok := value.([]interface{})
	if !ok {
		return nil
	}
	values := make([]string, 0, len(rawValues))
	for _, rawValue := range rawValues {
		values = append(values, fmt.Sprint(rawValue))
	}
	return values
}
