package nodes

import (
	"context"
	"testing"

	"github.com/google/go-cmp/cmp"
	v1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/client-go/kubernetes/fake"
	k8stesting "k8s.io/client-go/testing"
)

const annotationKey = "scheduling.task.policydriven.unimi.it/wallContexts"

func node(name string, annotations map[string]string) *v1.Node {
	return &v1.Node{
		ObjectMeta: metav1.ObjectMeta{
			Name:            name,
			Annotations:     annotations,
			ResourceVersion: "1",
		},
	}
}

func TestGetNilNode(t *testing.T) {
	if got := Get(nil, annotationKey); got != nil {
		t.Fatalf("expected nil, got %v", got)
	}
}

func TestGetMissingAnnotation(t *testing.T) {
	n := node("n1", nil)
	if got := Get(n, annotationKey); got != nil {
		t.Fatalf("expected nil, got %v", got)
	}
}

func TestGetEmptyAnnotation(t *testing.T) {
	n := node("n1", map[string]string{annotationKey: ""})
	if got := Get(n, annotationKey); got != nil {
		t.Fatalf("expected nil, got %v", got)
	}
}

func TestGetValid(t *testing.T) {
	n := node("n1", map[string]string{annotationKey: `["Ferrari","Ford"]`})
	got := Get(n, annotationKey)
	want := []string{"Ferrari", "Ford"}
	if diff := cmp.Diff(want, got); diff != "" {
		t.Fatalf("unexpected result:\n%s", diff)
	}
}

func TestGetMalformedAnnotationTreatedAsEmpty(t *testing.T) {
	n := node("n1", map[string]string{annotationKey: "not json"})
	if got := Get(n, annotationKey); got != nil {
		t.Fatalf("expected nil for malformed annotation, got %v", got)
	}
}

func TestUpdateEmptyCtxStarIsNoop(t *testing.T) {
	n := node("n1", nil)
	clientset := fake.NewSimpleClientset(n)

	if err := Update(context.Background(), clientset, "n1", annotationKey, nil); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	got, err := clientset.CoreV1().Nodes().Get(context.Background(), "n1", metav1.GetOptions{})
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := got.Annotations[annotationKey]; ok {
		t.Fatalf("expected no annotation to be written, got %v", got.Annotations)
	}
}

func TestUpdateSetsAnnotationOnCleanNode(t *testing.T) {
	n := node("n1", nil)
	clientset := fake.NewSimpleClientset(n)

	if err := Update(context.Background(), clientset, "n1", annotationKey, []string{"Ford"}); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	got, err := clientset.CoreV1().Nodes().Get(context.Background(), "n1", metav1.GetOptions{})
	if err != nil {
		t.Fatal(err)
	}
	if diff := cmp.Diff([]string{"Ford"}, Get(got, annotationKey)); diff != "" {
		t.Fatalf("unexpected Lambda(n1):\n%s", diff)
	}
}

func TestUpdateMergesWithExisting(t *testing.T) {
	n := node("n1", map[string]string{annotationKey: `["Ford"]`})
	clientset := fake.NewSimpleClientset(n)

	if err := Update(context.Background(), clientset, "n1", annotationKey, []string{"Finance"}); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	got, err := clientset.CoreV1().Nodes().Get(context.Background(), "n1", metav1.GetOptions{})
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"Finance", "Ford"} // sorted
	if diff := cmp.Diff(want, Get(got, annotationKey)); diff != "" {
		t.Fatalf("unexpected Lambda(n1):\n%s", diff)
	}
}

func TestUpdateDeduplicates(t *testing.T) {
	n := node("n1", map[string]string{annotationKey: `["Ford"]`})
	clientset := fake.NewSimpleClientset(n)

	if err := Update(context.Background(), clientset, "n1", annotationKey, []string{"Ford"}); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	got, err := clientset.CoreV1().Nodes().Get(context.Background(), "n1", metav1.GetOptions{})
	if err != nil {
		t.Fatal(err)
	}
	if diff := cmp.Diff([]string{"Ford"}, Get(got, annotationKey)); diff != "" {
		t.Fatalf("unexpected Lambda(n1):\n%s", diff)
	}
}

func TestUpdateNodeNotFound(t *testing.T) {
	clientset := fake.NewSimpleClientset()

	err := Update(context.Background(), clientset, "does-not-exist", annotationKey, []string{"Ford"})
	if err == nil {
		t.Fatal("expected error, got nil")
	}
}

func TestUpdateRetriesOnConflict(t *testing.T) {
	n := node("n1", map[string]string{annotationKey: `["Ford"]`})
	clientset := fake.NewSimpleClientset(n)

	attempts := 0
	clientset.PrependReactor("update", "nodes", func(action k8stesting.Action) (bool, runtime.Object, error) {
		attempts++
		if attempts == 1 {
			gvr := schema.GroupResource{Group: "", Resource: "nodes"}
			return true, nil, apierrors.NewConflict(gvr, "n1", nil)
		}
		return false, nil, nil // let the second attempt fall through to the fake's default handling
	})

	if err := Update(context.Background(), clientset, "n1", annotationKey, []string{"Finance"}); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if attempts < 2 {
		t.Fatalf("expected Update to retry after a conflict, got %d attempt(s)", attempts)
	}

	got, err := clientset.CoreV1().Nodes().Get(context.Background(), "n1", metav1.GetOptions{})
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"Finance", "Ford"}
	if diff := cmp.Diff(want, Get(got, annotationKey)); diff != "" {
		t.Fatalf("unexpected Lambda(n1) after retry:\n%s", diff)
	}
}
