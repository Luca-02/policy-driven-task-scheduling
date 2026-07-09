package datasets

import (
	"context"
	"net/http"
)

// DatasetInfo holds the data returned by the dataset-service for a single dataset.
type DatasetInfo struct {
	Name   string   `json:"name"`
	SizeMB int      `json:"size_mb"`
	Nodes  []string `json:"nodes"`
}

// QueryRequest holds the request body sent to the dataset-service when querying for datasets.
type QueryRequest struct {
	Keys []string `json:"keys"`
}

// DatasetClient is a client for the dataset-service.
type DatasetClient struct {
	baseURL string
	http    *http.Client
}

// DatasetQuerier acts as a client for the dataset-service.
type DatasetQuerier interface {
	Query(ctx context.Context, keys []string) ([]DatasetInfo, error)
}
