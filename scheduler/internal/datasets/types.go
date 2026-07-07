package datasets

import (
	"context"
	"net/http"
)

type DatasetInfo struct {
	Name   string   `json:"name"`
	SizeMB int      `json:"size_mb"`
	Nodes  []string `json:"nodes"`
}

type QueryRequest struct {
	Keys []string `json:"keys"`
}

type DatasetClient struct {
	baseURL string
	http    *http.Client
}

// DatasetQuerier acts as a client for the dataset-service.
type DatasetQuerier interface {
	Query(ctx context.Context, keys []string) ([]DatasetInfo, error)
}
