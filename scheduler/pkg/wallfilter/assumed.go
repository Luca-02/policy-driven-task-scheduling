package wallfilter

import (
	"sort"
	"sync"
	"time"

	"k8s.io/apimachinery/pkg/types"
)

// assumedLambda closes the window between a scheduling decision and the moment
// that decision becomes visible in Lambda(n).
//
// Filter evaluates c_wall against the node snapshot the scheduling cycle took
// from the informer cache, while the deposit
//
//	Lambda(f(t)) <- Lambda(f(t)) union ctx*(t)
//
// is written through the API in PostBind. Two delays sit in between. The
// binding cycle (PreBind/Bind/PostBind) runs asynchronously with respect to the
// scheduling cycle, so the next pod can be filtered before the previous pod's
// PostBind has run at all; and once written, the new annotation still needs
// informer propagation before any snapshot reports it. A burst of pods released
// onto a freshly sanitized node can therefore all be filtered against the same
// empty Lambda and land together, depositing mutually conflicting contexts on
// one node — a TOCTOU violation of c_wall that the model, which assumes the
// deposit is atomic with the placement, does not admit.
//
// This store records ctx*(t) in Reserve, which the framework runs
// synchronously inside the scheduling cycle and therefore strictly before any
// later pod's Filter. Filter then evaluates c_wall against the snapshot value
// union the contexts assumed for that node, so a deposit that is decided but
// not yet observable is still honoured.
//
// An entry leaves the store when any of the following happens:
//   - Unreserve is called, meaning the bind failed and nothing was deposited;
//   - the snapshot catches up and already reports the context, the persisted
//     Lambda having become authoritative;
//   - the TTL expires, a backstop for an entry that neither committed nor
//     rolled back (for instance a PostBind whose API write failed). The TTL
//     only has to outlast informer propagation, so it is generously above it.
type assumedLambda struct {
	mu     sync.Mutex
	ttl    time.Duration
	now    func() time.Time
	byNode map[string]map[string]*assumedEntry
	byPod  map[types.UID]podAssumption
}

// assumedEntry counts how many pending pods assumed a context on a node, so
// rolling one back does not drop an assumption another pod still needs.
type assumedEntry struct {
	count int
	at    time.Time
}

type podAssumption struct {
	node     string
	contexts []string
	at       time.Time
}

func newAssumedLambda(ttl time.Duration) *assumedLambda {
	return &assumedLambda{
		ttl:    ttl,
		now:    time.Now,
		byNode: make(map[string]map[string]*assumedEntry),
		byPod:  make(map[types.UID]podAssumption),
	}
}

// assume records that pod is about to deposit contexts on node.
func (a *assumedLambda) assume(podUID types.UID, node string, contexts []string) {
	if len(contexts) == 0 {
		return
	}

	a.mu.Lock()
	defer a.mu.Unlock()
	a.pruneLocked()

	// Reserve can run again for the same pod after a failed attempt; drop the
	// stale assumption before recording the new one.
	a.forgetLocked(podUID)

	perNode := a.byNode[node]
	if perNode == nil {
		perNode = make(map[string]*assumedEntry)
		a.byNode[node] = perNode
	}

	now := a.now()
	for _, c := range contexts {
		if entry := perNode[c]; entry != nil {
			entry.count++
			entry.at = now
		} else {
			perNode[c] = &assumedEntry{count: 1, at: now}
		}
	}

	stored := make([]string, len(contexts))
	copy(stored, contexts)
	a.byPod[podUID] = podAssumption{node: node, contexts: stored, at: now}
}

// forget drops pod's assumption, for Unreserve: the bind will not happen, so
// nothing is going to be deposited on its behalf.
func (a *assumedLambda) forget(podUID types.UID) {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.forgetLocked(podUID)
}

func (a *assumedLambda) forgetLocked(podUID types.UID) {
	assumption, ok := a.byPod[podUID]
	if !ok {
		return
	}
	delete(a.byPod, podUID)

	perNode := a.byNode[assumption.node]
	if perNode == nil {
		return
	}
	for _, c := range assumption.contexts {
		entry := perNode[c]
		if entry == nil {
			continue
		}
		entry.count--
		if entry.count <= 0 {
			delete(perNode, c)
		}
	}
	if len(perNode) == 0 {
		delete(a.byNode, assumption.node)
	}
}

// merge returns Lambda(n) as Filter should see it: the snapshot value union the
// contexts assumed for that node. Contexts the snapshot already reports are
// dropped from the store, the persisted annotation having caught up. The result
// is sorted so log lines and conflict queries are stable.
func (a *assumedLambda) merge(node string, snapshot []string) []string {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.pruneLocked()

	perNode := a.byNode[node]
	if len(perNode) == 0 {
		return snapshot
	}

	inSnapshot := make(map[string]struct{}, len(snapshot))
	for _, c := range snapshot {
		inSnapshot[c] = struct{}{}
	}

	extra := make([]string, 0, len(perNode))
	for c := range perNode {
		if _, seen := inSnapshot[c]; seen {
			delete(perNode, c)
			continue
		}
		extra = append(extra, c)
	}
	if len(perNode) == 0 {
		delete(a.byNode, node)
	}
	if len(extra) == 0 {
		return snapshot
	}

	merged := make([]string, 0, len(snapshot)+len(extra))
	merged = append(merged, snapshot...)
	merged = append(merged, extra...)
	sort.Strings(merged)

	return merged
}

// pruneLocked drops entries older than the TTL. Callers must hold the mutex.
func (a *assumedLambda) pruneLocked() {
	if a.ttl <= 0 {
		return
	}
	cutoff := a.now().Add(-a.ttl)

	for node, perNode := range a.byNode {
		for c, entry := range perNode {
			if entry.at.Before(cutoff) {
				delete(perNode, c)
			}
		}
		if len(perNode) == 0 {
			delete(a.byNode, node)
		}
	}

	for uid, assumption := range a.byPod {
		if assumption.at.Before(cutoff) {
			delete(a.byPod, uid)
		}
	}
}
