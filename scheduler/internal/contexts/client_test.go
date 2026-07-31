package contexts

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/google/go-cmp/cmp"
)

func TestContextClientCheckWallConflictsNoConflict(t *testing.T) {
	wantPath := "/issuer-auths/i1/wall-check"

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != wantPath || r.Method != http.MethodPost {
			t.Errorf("unexpected request: %s %s", r.Method, r.URL.Path)
		}

		body, err := io.ReadAll(r.Body)
		if err != nil {
			t.Fatal(err)
		}

		var req WallCheckRequest
		if err := json.Unmarshal(body, &req); err != nil {
			t.Fatal(err)
		}
		if diff := cmp.Diff([]string{"Finance"}, req.Contexts); diff != "" {
			t.Fatalf("unexpected request body:\n%s", diff)
		}

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(WallCheckResponse{Conflicts: []Conflict{}})
	}))
	defer srv.Close()

	client := &ContextClient{baseURL: srv.URL, http: srv.Client()}

	got, err := client.CheckWallConflicts(context.Background(), "i1", []string{"Finance"})
	if err != nil {
		t.Fatalf("CheckWallConflicts returned error: %v", err)
	}
	if len(got) != 0 {
		t.Fatalf("expected no conflicts, got %v", got)
	}
}

func TestContextClientCheckWallConflictsFound(t *testing.T) {
	wantPath := "/issuer-auths/i1/wall-check"
	want := []Conflict{{ContextA: "Ferrari", ContextB: "Ford"}}

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != wantPath || r.Method != http.MethodPost {
			t.Errorf("unexpected request: %s %s", r.Method, r.URL.Path)
		}

		body, err := io.ReadAll(r.Body)
		if err != nil {
			t.Fatal(err)
		}

		var req WallCheckRequest
		if err := json.Unmarshal(body, &req); err != nil {
			t.Fatal(err)
		}
		if diff := cmp.Diff([]string{"Ferrari"}, req.Contexts); diff != "" {
			t.Fatalf("unexpected request body:\n%s", diff)
		}

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(WallCheckResponse{Conflicts: want})
	}))
	defer srv.Close()

	client := &ContextClient{baseURL: srv.URL, http: srv.Client()}

	got, err := client.CheckWallConflicts(context.Background(), "i1", []string{"Ferrari"})
	if err != nil {
		t.Fatalf("CheckWallConflicts returned error: %v", err)
	}
	if diff := cmp.Diff(want, got); diff != "" {
		t.Fatalf("unexpected result:\n%s", diff)
	}
}

func TestContextClientCheckWallConflictsIssuerNameEscaped(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.EscapedPath() != "/issuer-auths/issuer%20with%20space/wall-check" {
			t.Errorf("unexpected escaped path: %s", r.URL.EscapedPath())
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(WallCheckResponse{Conflicts: []Conflict{}})
	}))
	defer srv.Close()

	client := &ContextClient{baseURL: srv.URL, http: srv.Client()}

	if _, err := client.CheckWallConflicts(context.Background(), "issuer with space", nil); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestContextClientCheckWallConflictsIssuerNotFound(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "not found", http.StatusNotFound)
	}))
	defer srv.Close()

	client := &ContextClient{baseURL: srv.URL, http: srv.Client()}

	_, err := client.CheckWallConflicts(context.Background(), "ghost", nil)
	if err == nil {
		t.Fatal("expected error, got nil")
	}
}

func TestContextClientCheckWallConflictsServerError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "internal error", http.StatusInternalServerError)
	}))
	defer srv.Close()

	client := &ContextClient{baseURL: srv.URL, http: srv.Client()}

	_, err := client.CheckWallConflicts(context.Background(), "i1", nil)
	if err == nil {
		t.Fatal("expected error, got nil")
	}
}

func TestNewContextClientRejectsBadCA(t *testing.T) {
	if _, err := NewContextClient("https://x", "/nonexistent/ca.crt"); err == nil {
		t.Error("expected error for missing CA file, got nil")
	}
}

func TestNewContextClientRejectsEmptyBaseURL(t *testing.T) {
	if _, err := NewContextClient("", "/nonexistent/ca.crt"); err == nil {
		t.Error("expected error for empty base URL, got nil")
	}
}
