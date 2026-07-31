package datasets

import (
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"strings"
	"time"
)

const EndpointQuery = "/datasets/query"

// NewDatasetClient builds an HTTPS client that verifies the dataset-service
// certificate against the given CA (no InsecureSkipVerify).
func NewDatasetClient(baseURL string, caCertFile string) (*DatasetClient, error) {
	if baseURL == "" {
		return nil, fmt.Errorf("dataset-service base URL is empty")
	}

	caCert, err := os.ReadFile(caCertFile)
	if err != nil {
		return nil, fmt.Errorf("reading CA cert %q: %w", caCertFile, err)
	}

	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(caCert) {
		return nil, fmt.Errorf("no valid certificate found in %q", caCertFile)
	}

	return &DatasetClient{
		baseURL: strings.TrimRight(baseURL, "/"),
		http: &http.Client{
			Timeout: 10 * time.Second,
			Transport: &http.Transport{
				TLSClientConfig: &tls.Config{RootCAs: pool},
			},
		},
	}, nil
}

// Query queries the dataset-service for the given keys.
func (c *DatasetClient) Query(ctx context.Context, keys []string) ([]DatasetInfo, error) {
	body, err := json.Marshal(QueryRequest{Keys: keys})
	if err != nil {
		return nil, err
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+EndpointQuery, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}

	req.Header.Set("Content-Type", "application/json")

	resp, err := c.http.Do(req)
	if err != nil {
		return nil, fmt.Errorf("dataset-service request failed: %w", err)
	}

	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("dataset-service returned status %d", resp.StatusCode)
	}

	var infos []DatasetInfo
	if err := json.NewDecoder(resp.Body).Decode(&infos); err != nil {
		return nil, fmt.Errorf("decoding dataset-service response: %w", err)
	}

	return infos, nil
}
