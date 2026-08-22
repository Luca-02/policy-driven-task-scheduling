package nodeproperties

import (
	"context"
	"testing"
	"time"

	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
	dynamicfake "k8s.io/client-go/dynamic/fake"

	"github.com/Luca-02/policy-driven-task-scheduling/scheduler/internal/config"
)

func testConfig() config.Config {
	return config.Config{
		Group:                      config.DefaultGroup,
		CrdVersion:                 config.DefaultCrdVersion,
		NodePropertyResourcePlural: config.DefaultNodePropertyResourcePlural,
	}
}

func newNodeProperty(name string, weight *float64, levelCount int) *unstructured.Unstructured {
	levelObjs := make([]any, levelCount)
	for i := range levelObjs {
		// Each level is represented as an empty object in the "levels" list
		levelObjs[i] = map[string]any{}
	}

	spec := map[string]any{"levels": levelObjs}
	if weight != nil {
		spec["weight"] = *weight
	}

	return &unstructured.Unstructured{Object: map[string]any{
		"apiVersion": config.DefaultGroup + "/" + config.DefaultCrdVersion,
		"kind":       "NodeProperty",
		"metadata":   map[string]any{"name": name},
		"spec":       spec,
	}}
}

func floatPtr(f float64) *float64 { return &f }

func newFakeClient(objs ...*unstructured.Unstructured) *dynamicfake.FakeDynamicClient {
	scheme := runtime.NewScheme()
	gvr := gvrFrom(testConfig())
	listKinds := map[schema.GroupVersionResource]string{gvr: "NodePropertyList"}

	var runtimeObjs []runtime.Object
	for _, o := range objs {
		runtimeObjs = append(runtimeObjs, o)
	}
	return dynamicfake.NewSimpleDynamicClientWithCustomListKinds(scheme, listKinds, runtimeObjs...)
}

func TestCacheSyncsExistingObjects(t *testing.T) {
	client := newFakeClient(
		newNodeProperty("security", floatPtr(2.0), 3),
		newNodeProperty("computation", nil, 2), // no weight -> defaults to 1
	)

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	c, err := newCacheFromClient(ctx, testConfig(), client)
	if err != nil {
		t.Fatalf("newCacheFromClient returned error: %v", err)
	}

	info, ok := c.Get("security")
	if !ok {
		t.Fatal("expected 'security' to be found")
	}
	if info.MaxLevel != 3 {
		t.Errorf("security MaxLevel = %d, want 3", info.MaxLevel)
	}
	if info.Weight != 2.0 {
		t.Errorf("security Weight = %v, want 2.0", info.Weight)
	}

	info, ok = c.Get("computation")
	if !ok {
		t.Fatal("expected 'computation' to be found")
	}
	if info.MaxLevel != 2 {
		t.Errorf("computation MaxLevel = %d, want 2", info.MaxLevel)
	}
	if info.Weight != 1.0 {
		t.Errorf("computation Weight (default) = %v, want 1.0", info.Weight)
	}
}

func TestCacheGetUnknownPropertyReturnsFalse(t *testing.T) {
	client := newFakeClient()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	c, err := newCacheFromClient(ctx, testConfig(), client)
	if err != nil {
		t.Fatalf("newCacheFromClient returned error: %v", err)
	}

	if _, ok := c.Get("nonexistent"); ok {
		t.Error("expected 'nonexistent' to not be found")
	}
}

func TestExtractInfoEmptyLevelsIsMaxZero(t *testing.T) {
	info := extractInfo(newNodeProperty("empty", nil, 0))
	if info.Name != "empty" {
		t.Errorf("Name = %q, want %q", info.Name, "empty")
	}
	if info.MaxLevel != 0 {
		t.Errorf("MaxLevel = %d, want 0", info.MaxLevel)
	}
	if info.Weight != 1.0 {
		t.Errorf("Weight = %v, want 1.0 (default)", info.Weight)
	}
}
