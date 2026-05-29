package controller

import (
	"testing"

	"github.com/policy-driven-task-scheduling/node-property-controller/internal/config"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
)

func TestParseNodeExtractsAttributesAndProperties(t *testing.T) {
	cfg := config.Config{AttributePrefix: "attribute.node.policydriven.unimi.it", PropertyPrefix: "property.node.policydriven.unimi.it"}
	node := ParseNode("worker-1", map[string]string{
		"attribute.node.policydriven.unimi.it/cpu": "16",
		"property.node.policydriven.unimi.it/sec":  "2",
		"unrelated": "ignored",
	}, cfg)

	if node.Attributes["cpu"] != "16" {
		t.Fatalf("expected cpu attribute to be extracted, got %#v", node.Attributes)
	}
	if node.Properties["sec"] != 2 {
		t.Fatalf("expected sec property to be extracted, got %#v", node.Properties)
	}
}

func TestParseProperty(t *testing.T) {
	obj := &unstructured.Unstructured{Object: map[string]interface{}{
		"spec": map[string]interface{}{
			"levels": []interface{}{
				map[string]interface{}{
					"level": int64(1),
					"disjunction": []interface{}{
						map[string]interface{}{
							"clause": []interface{}{
								map[string]interface{}{"key": "cpu", "operator": "Gte", "values": []interface{}{"8"}},
							},
						},
					},
				},
			},
		},
	}}
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
