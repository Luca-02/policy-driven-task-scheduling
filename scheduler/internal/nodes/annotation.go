package nodes

import (
	"context"
	"encoding/json"
	"fmt"
	"sort"

	v1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/util/retry"
)

// unionSorted returns the sorted union of a and b, deduplicated. Sorted so the
// encoded annotation is stable across calls that produce the same logical set,
// which keeps Node diffs/events readable.
func unionSorted(a, b []string) []string {
	set := make(map[string]struct{}, len(a)+len(b))
	for _, x := range a {
		set[x] = struct{}{}
	}
	for _, x := range b {
		set[x] = struct{}{}
	}

	result := make([]string, 0, len(set))
	for x := range set {
		result = append(result, x)
	}
	sort.Strings(result)

	return result
}

// Get returns Lambda(n) for the given node, decoded from its annotationKey annotation.
func Get(node *v1.Node, annotationKey string) []string {
	if node == nil {
		return nil
	}

	raw, ok := node.Annotations[annotationKey]
	if !ok || raw == "" {
		return nil
	}

	var contexts []string
	if err := json.Unmarshal([]byte(raw), &contexts); err != nil {
		return nil
	}

	return contexts
}

// Update deposits ctxStar (ctx*(t) for the task just bound) onto Lambda(n) for nodeName,
// implementing the model's only mutation of Lambda:
//
//	f(t) != bot => Lambda(f(t)) <- Lambda(f(t)) union ctx*(t)
//
// Lambda(n) can only grow through this call, never shrink. A no-op if ctxStar is empty (a task
// requesting only public datasets deposits nothing).
//
// Reads the node fresh (not from any cache) immediately before writing, and retries on a
// conflicting concurrent write (e.g. another PostBind, or a Sanitize pass, touching the
// same node in between) by re-reading and reapplying the merge.
func Update(ctx context.Context, clientset kubernetes.Interface, nodeName, annotationKey string, ctxStar []string) error {
	// No-op if ctxStar is empty, since only public datasets are requested.
	if len(ctxStar) == 0 {
		return nil
	}

	return retry.RetryOnConflict(retry.DefaultBackoff, func() error {
		node, err := clientset.CoreV1().Nodes().Get(ctx, nodeName, metav1.GetOptions{})
		if err != nil {
			return fmt.Errorf("getting node %q: %w", nodeName, err)
		}

		merged := unionSorted(Get(node, annotationKey), ctxStar)

		encoded, err := json.Marshal(merged)
		if err != nil {
			return fmt.Errorf("encoding Lambda(%s): %w", nodeName, err)
		}

		if node.Annotations == nil {
			node.Annotations = map[string]string{}
		}

		node.Annotations[annotationKey] = string(encoded)

		if _, err := clientset.CoreV1().Nodes().Update(ctx, node, metav1.UpdateOptions{}); err != nil {
			return fmt.Errorf("updating node %q: %w", nodeName, err)
		}

		return nil
	})
}
