package controller

import (
	"strings"
	"testing"

	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
)

const (
	testAttributePrefix = "attribute.node.policydriven.unimi.it"
	testPropertyPrefix  = "property.node.policydriven.unimi.it"
)

func TestParseNodeExtractsAttributesAndProperties(t *testing.T) {
	node := ParseNode("worker-1", map[string]string{
		"attribute.node.policydriven.unimi.it/cpu": "16",
		"attribute.node.policydriven.unimi.it/gpu": "nvidia",
		"property.node.policydriven.unimi.it/sec":  "2",
		"property.node.policydriven.unimi.it/bad":  "not-int",
		"unrelated": "ignored",
	}, testAttributePrefix, testPropertyPrefix)

	if node.Attributes["cpu"] != "16" || node.Attributes["gpu"] != "nvidia" {
		t.Fatalf("expected attributes to be extracted, got %#v", node.Attributes)
	}
	if _, ok := node.Attributes["unrelated"]; ok {
		t.Fatalf("unexpected unrelated attribute: %#v", node.Attributes)
	}
	if node.Properties["sec"] != 2 {
		t.Fatalf("expected sec property to be extracted, got %#v", node.Properties)
	}
	if _, ok := node.Properties["bad"]; ok {
		t.Fatalf("non-integer property labels must be ignored, got %#v", node.Properties)
	}
}

func TestParsePropertyBuildsDNFModel(t *testing.T) {
	obj := propertyObject([]interface{}{
		map[string]interface{}{
			"level": int64(1),
			"disjunction": []interface{}{
				map[string]interface{}{
					"clause": []interface{}{
						map[string]interface{}{"key": "cpu", "operator": "Gte", "values": []interface{}{"8"}},
						map[string]interface{}{"key": "arch", "operator": "Eq", "values": []interface{}{"amd64"}},
					},
				},
				map[string]interface{}{
					"clause": []interface{}{
						map[string]interface{}{"key": "gpu", "operator": "Exists"},
					},
				},
			},
		},
	})
	property, err := ParseProperty("computation", obj)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	level, err := property.MaxLevel(map[string]string{"cpu": "16", "arch": "amd64"})
	if err != nil {
		t.Fatalf("unexpected evaluation error: %v", err)
	}
	if level != 1 {
		t.Fatalf("expected first clause to satisfy level 1, got %d", level)
	}

	level, err = property.MaxLevel(map[string]string{"gpu": "true"})
	if err != nil {
		t.Fatalf("unexpected evaluation error: %v", err)
	}
	if level != 1 {
		t.Fatalf("expected second OR clause to satisfy level 1, got %d", level)
	}
}

func TestParsePropertyAcceptsIntOrStringValues(t *testing.T) {
	obj := propertyObject([]interface{}{
		map[string]interface{}{
			"level": int64(1),
			"disjunction": []interface{}{
				map[string]interface{}{
					"clause": []interface{}{
						map[string]interface{}{"key": "cpu", "operator": "Gte", "values": []interface{}{int64(8)}},
					},
				},
			},
		},
	})
	property, err := ParseProperty("computation", obj)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	level, err := property.MaxLevel(map[string]string{"cpu": "16"})
	if err != nil {
		t.Fatalf("unexpected evaluation error: %v", err)
	}
	if level != 1 {
		t.Fatalf("expected level 1, got %d", level)
	}
}

func TestParsePropertyValidationErrors(t *testing.T) {
	tests := []struct {
		name    string
		obj     *unstructured.Unstructured
		message string
	}{
		{name: "missing levels", obj: &unstructured.Unstructured{Object: map[string]interface{}{"spec": map[string]interface{}{}}}, message: "spec.levels is required"},
		{name: "bad level", obj: propertyObject([]interface{}{map[string]interface{}{"level": "one", "disjunction": []interface{}{}}}), message: "must be an integer"},
		{name: "bad disjunction", obj: propertyObject([]interface{}{map[string]interface{}{"level": int64(1), "disjunction": "bad"}}), message: "disjunction must be a list"},
		{
			name: "bad operator",
			obj: propertyObject([]interface{}{
				map[string]interface{}{
					"level": int64(1),
					"disjunction": []interface{}{
						map[string]interface{}{
							"clause": []interface{}{
								map[string]interface{}{"key": "cpu", "operator": "Between"},
							},
						},
					},
				},
			}),
			message: "unknown operator",
		},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			_, err := ParseProperty("bad", test.obj)
			if err == nil || !strings.Contains(err.Error(), test.message) {
				t.Fatalf("expected error containing %q, got %v", test.message, err)
			}
		})
	}
}

func propertyObject(levels []interface{}) *unstructured.Unstructured {
	return &unstructured.Unstructured{Object: map[string]interface{}{
		"spec": map[string]interface{}{
			"levels": levels,
		},
	}}
}
