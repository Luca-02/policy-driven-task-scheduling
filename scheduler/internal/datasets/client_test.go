package datasets

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/google/go-cmp/cmp"
)

func TestDatasetClientQuery(t *testing.T) {
	d1 := DatasetInfo{Name: "d1", SizeMB: 1024, Nodes: []string{"n1"}}
	d2 := DatasetInfo{Name: "d2", SizeMB: 2048, Nodes: []string{"n2"}}

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != EndpointQuery || r.Method != http.MethodPost {
			t.Errorf("unexpected request: %s %s", r.Method, r.URL.Path)
		}

		body, err := io.ReadAll(r.Body)
		if err != nil {
			t.Fatal(err)
		}

		var req QueryRequest
		if err := json.Unmarshal(body, &req); err != nil {
			t.Fatal(err)
		}

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode([]DatasetInfo{d1, d2})
	}))
	defer srv.Close()

	client := &DatasetClient{baseURL: srv.URL, http: srv.Client()}

	infos, err := client.Query(context.Background(), []string{"d1", "d2"})
	if err != nil {
		t.Fatalf("Query returned error: %v", err)
	}

	want := []DatasetInfo{d1, d2}
	if diff := cmp.Diff(want, infos); diff != "" {
		t.Fatalf("unexpected result:\n%s", diff)
	}
}

func TestDatasetClientQueryServerError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "internal error", http.StatusInternalServerError)
	}))
	defer srv.Close()

	client := &DatasetClient{
		baseURL: srv.URL,
		http:    srv.Client(),
	}

	_, err := client.Query(context.Background(), []string{"d1"})
	if err == nil {
		t.Fatal("expected error, got nil")
	}
}

func TestDatasetClientQueryEmptyResult(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode([]DatasetInfo{})
	}))
	defer srv.Close()

	client := &DatasetClient{baseURL: srv.URL, http: srv.Client()}

	got, err := client.Query(context.Background(), []string{"missing"})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if len(got) != 0 {
		t.Fatalf("expected empty result, got %v", got)
	}
}

func TestNewDatasetClientRejectsBadCA(t *testing.T) {
	if _, err := NewDatasetClient("https://x", "/nonexistent/ca.crt"); err == nil {
		t.Error("expected error for missing CA file, got nil")
	}
}
