package wallfilter

import (
	"context"
	"errors"
	"testing"

	"github.com/google/go-cmp/cmp"
	fwk "k8s.io/kube-scheduler/framework"

	"github.com/Luca-02/policy-driven-task-scheduling/scheduler/internal/contexts"
)

type fakeWallChecker struct {
	conflicts []contexts.Conflict
	err       error

	called    bool
	gotIssuer string
	gotLambda []string
}

func (f *fakeWallChecker) CheckWallConflicts(_ context.Context, issuer string, lambda []string) ([]contexts.Conflict, error) {
	f.called = true
	f.gotIssuer = issuer
	f.gotLambda = lambda
	return f.conflicts, f.err
}

func TestCheckWallEmptyLambdaSkipsClient(t *testing.T) {
	client := &fakeWallChecker{conflicts: []contexts.Conflict{{ContextA: "Ferrari", ContextB: "Ford"}}}

	status := checkWall(context.Background(), client, "i1", nil)

	if status.Code() != fwk.Success {
		t.Fatalf("expected Success, got %v (%s)", status.Code(), status.Message())
	}
	if client.called {
		t.Fatal("expected context-service not to be called when Lambda(n) is empty")
	}
}

// TestCheckWallEmptyIssuerStillCallsClient locks in the current
// behaviour: checkWall no longer special-cases an empty issuer (only
// an empty Lambda(n) skips the call). Whether an empty issuer is
// possible in practice is left to the CRD/caller, not to this
// function.
func TestCheckWallEmptyIssuerStillCallsClient(t *testing.T) {
	client := &fakeWallChecker{conflicts: nil}

	status := checkWall(context.Background(), client, "", []string{"Ford"})

	if status.Code() != fwk.Success {
		t.Fatalf("expected Success, got %v (%s)", status.Code(), status.Message())
	}
	if !client.called {
		t.Fatal("expected context-service to be called even with an empty issuer")
	}
	if client.gotIssuer != "" {
		t.Errorf("unexpected issuer passed: %q", client.gotIssuer)
	}
}

func TestCheckWallNoConflictsSatisfied(t *testing.T) {
	client := &fakeWallChecker{conflicts: nil}

	status := checkWall(context.Background(), client, "i1", []string{"Finance"})

	if status.Code() != fwk.Success {
		t.Fatalf("expected Success, got %v (%s)", status.Code(), status.Message())
	}
	if !client.called {
		t.Fatal("expected context-service to be called")
	}
	if client.gotIssuer != "i1" {
		t.Errorf("unexpected issuer passed: %q", client.gotIssuer)
	}
	if diff := cmp.Diff([]string{"Finance"}, client.gotLambda); diff != "" {
		t.Errorf("unexpected lambda passed:\n%s", diff)
	}
}

func TestCheckWallConflictFoundIsUnschedulable(t *testing.T) {
	client := &fakeWallChecker{conflicts: []contexts.Conflict{{ContextA: "Ferrari", ContextB: "Ford"}}}

	status := checkWall(context.Background(), client, "i1", []string{"Ford"})

	if status.Code() != fwk.Unschedulable {
		t.Fatalf("expected Unschedulable, got %v (%s)", status.Code(), status.Message())
	}
}

func TestCheckWallClientErrorIsError(t *testing.T) {
	client := &fakeWallChecker{err: errors.New("context-service unreachable")}

	status := checkWall(context.Background(), client, "i1", []string{"Ford"})

	if status.Code() != fwk.Error {
		t.Fatalf("expected Error, got %v (%s)", status.Code(), status.Message())
	}
}

func TestParseCtxStarEmptyIsNil(t *testing.T) {
	got, err := parseCtxStar("")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != nil {
		t.Fatalf("expected nil, got %v", got)
	}
}

func TestParseCtxStarValid(t *testing.T) {
	got, err := parseCtxStar(`["Ferrari","Finance"]`)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	want := []string{"Ferrari", "Finance"}
	if diff := cmp.Diff(want, got); diff != "" {
		t.Fatalf("unexpected result:\n%s", diff)
	}
}

func TestParseCtxStarMalformed(t *testing.T) {
	_, err := parseCtxStar("not json")
	if err == nil {
		t.Fatal("expected error, got nil")
	}
}
