package wallfilter

import (
	"testing"
	"time"

	"k8s.io/apimachinery/pkg/types"
)

// fakeClock lets the TTL be exercised without sleeping.
type fakeClock struct{ t time.Time }

func (c *fakeClock) now() time.Time          { return c.t }
func (c *fakeClock) advance(d time.Duration) { c.t = c.t.Add(d) }

func newTestStore(ttl time.Duration) (*assumedLambda, *fakeClock) {
	clock := &fakeClock{t: time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)}
	store := newAssumedLambda(ttl)
	store.now = clock.now
	return store, clock
}

func contains(list []string, want string) bool {
	for _, x := range list {
		if x == want {
			return true
		}
	}
	return false
}

// The whole point of the store: a context deposited by a pod already reserved
// must be visible to the next pod's Filter even while the snapshot still
// reports the old (here empty) Lambda.
func TestAssumedContextIsVisibleBeforeSnapshotCatchesUp(t *testing.T) {
	store, _ := newTestStore(5 * time.Second)
	store.assume(types.UID("pod-a"), "node1", []string{"x05"})

	got := store.merge("node1", nil)
	if !contains(got, "x05") {
		t.Fatalf("expected assumed context x05 in merged Lambda, got %v", got)
	}
}

func TestMergeUnionsSnapshotAndAssumedSorted(t *testing.T) {
	store, _ := newTestStore(5 * time.Second)
	store.assume(types.UID("pod-a"), "node1", []string{"x05"})

	got := store.merge("node1", []string{"x09", "x01"})
	want := []string{"x01", "x05", "x09"}
	if len(got) != len(want) {
		t.Fatalf("expected %v, got %v", want, got)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("expected sorted %v, got %v", want, got)
		}
	}
}

func TestMergeIsUnaffectedForOtherNodes(t *testing.T) {
	store, _ := newTestStore(5 * time.Second)
	store.assume(types.UID("pod-a"), "node1", []string{"x05"})

	if got := store.merge("node2", nil); len(got) != 0 {
		t.Fatalf("expected no assumed contexts on node2, got %v", got)
	}
}

// Once the persisted annotation reports the context, the assumption has served
// its purpose and is dropped, so the store does not grow without bound.
func TestSnapshotCatchUpDropsAssumption(t *testing.T) {
	store, _ := newTestStore(5 * time.Second)
	store.assume(types.UID("pod-a"), "node1", []string{"x05"})

	if got := store.merge("node1", []string{"x05"}); len(got) != 1 || got[0] != "x05" {
		t.Fatalf("expected exactly [x05], got %v", got)
	}
	if perNode := store.byNode["node1"]; len(perNode) != 0 {
		t.Fatalf("expected assumption dropped after snapshot caught up, got %v", perNode)
	}
}

// Unreserve must stop a never-deposited context from constraining other pods.
func TestForgetRollsBackAssumption(t *testing.T) {
	store, _ := newTestStore(5 * time.Second)
	store.assume(types.UID("pod-a"), "node1", []string{"x05"})
	store.forget(types.UID("pod-a"))

	if got := store.merge("node1", nil); len(got) != 0 {
		t.Fatalf("expected no assumed contexts after rollback, got %v", got)
	}
}

// Two pods can assume the same context on the same node; rolling one back must
// not drop the other's still-pending assumption.
func TestForgetIsRefCounted(t *testing.T) {
	store, _ := newTestStore(5 * time.Second)
	store.assume(types.UID("pod-a"), "node1", []string{"x05"})
	store.assume(types.UID("pod-b"), "node1", []string{"x05"})

	store.forget(types.UID("pod-a"))
	if got := store.merge("node1", nil); !contains(got, "x05") {
		t.Fatalf("expected x05 still assumed for pod-b, got %v", got)
	}

	store.forget(types.UID("pod-b"))
	if got := store.merge("node1", nil); len(got) != 0 {
		t.Fatalf("expected x05 gone after both rollbacks, got %v", got)
	}
}

func TestReassumeSamePodReplacesPreviousAssumption(t *testing.T) {
	store, _ := newTestStore(5 * time.Second)
	store.assume(types.UID("pod-a"), "node1", []string{"x05"})
	// A retried scheduling cycle places the same pod elsewhere.
	store.assume(types.UID("pod-a"), "node2", []string{"x07"})

	if got := store.merge("node1", nil); len(got) != 0 {
		t.Fatalf("expected node1 assumption released, got %v", got)
	}
	if got := store.merge("node2", nil); !contains(got, "x07") {
		t.Fatalf("expected x07 assumed on node2, got %v", got)
	}
}

// The TTL is the backstop for an assumption that neither committed nor rolled
// back, so it must eventually stop constraining scheduling.
func TestAssumptionExpiresAfterTTL(t *testing.T) {
	store, clock := newTestStore(5 * time.Second)
	store.assume(types.UID("pod-a"), "node1", []string{"x05"})

	clock.advance(4 * time.Second)
	if got := store.merge("node1", nil); !contains(got, "x05") {
		t.Fatalf("expected x05 still assumed before TTL, got %v", got)
	}

	clock.advance(2 * time.Second)
	if got := store.merge("node1", nil); len(got) != 0 {
		t.Fatalf("expected x05 expired after TTL, got %v", got)
	}
	if len(store.byPod) != 0 {
		t.Fatalf("expected pod records pruned after TTL, got %v", store.byPod)
	}
}

func TestZeroTTLDisablesExpiry(t *testing.T) {
	store, clock := newTestStore(0)
	store.assume(types.UID("pod-a"), "node1", []string{"x05"})

	clock.advance(time.Hour)
	if got := store.merge("node1", nil); !contains(got, "x05") {
		t.Fatalf("expected no expiry when TTL is zero, got %v", got)
	}
}

func TestAssumeEmptyContextsIsNoop(t *testing.T) {
	store, _ := newTestStore(5 * time.Second)
	store.assume(types.UID("pod-a"), "node1", nil)

	if got := store.merge("node1", nil); len(got) != 0 {
		t.Fatalf("expected nothing assumed for empty ctx*, got %v", got)
	}
	if len(store.byPod) != 0 {
		t.Fatalf("expected no pod record for empty ctx*, got %v", store.byPod)
	}
}

func TestForgetUnknownPodIsNoop(t *testing.T) {
	store, _ := newTestStore(5 * time.Second)
	store.forget(types.UID("never-seen"))
}

// Filter runs concurrently across candidate nodes, so the store must be safe
// under simultaneous readers and writers.
func TestConcurrentAccessIsSafe(t *testing.T) {
	store, _ := newTestStore(5 * time.Second)
	done := make(chan struct{})

	go func() {
		for i := 0; i < 1000; i++ {
			store.assume(types.UID("pod-a"), "node1", []string{"x05"})
			store.forget(types.UID("pod-a"))
		}
		close(done)
	}()

	for i := 0; i < 1000; i++ {
		store.merge("node1", []string{"x01"})
	}
	<-done
}
