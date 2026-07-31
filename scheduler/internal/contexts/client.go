package contexts

import (
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"
)

const EndpointIssuerWallConflicts = "/issuer-auths/%s/wall-check"

// NewContextClient builds an HTTPS client that verifies the context-service
// certificate against the given CA (no InsecureSkipVerify).
func NewContextClient(baseURL string, caCertFile string) (*ContextClient, error) {
	if baseURL == "" {
		return nil, fmt.Errorf("context-service base URL is empty")
	}

	caCert, err := os.ReadFile(caCertFile)
	if err != nil {
		return nil, fmt.Errorf("reading CA cert %q: %w", caCertFile, err)
	}

	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(caCert) {
		return nil, fmt.Errorf("no valid certificate found in %q", caCertFile)
	}

	return &ContextClient{
		baseURL: strings.TrimRight(baseURL, "/"),
		http: &http.Client{
			Timeout: 10 * time.Second,
			Transport: &http.Transport{
				TLSClientConfig: &tls.Config{RootCAs: pool},
			},
		},
	}, nil
}

// CheckWallConflicts checks c_wall for the given issuer against lambda,
// the set of contexts already deposited on a candidate node (Lambda(n)
// in the model):
//
//	(auth(issuer) x lambda) intersect X_conf
//
// An empty result means c_wall is satisfied; a non-empty result lists every
// conflicting pair found. Returns ErrIssuerNotFound if context-service
// doesn't know the issuer.
func (c *ContextClient) CheckWallConflicts(ctx context.Context, issuer string, lambda []string) ([]Conflict, error) {
	body, err := json.Marshal(WallCheckRequest{Contexts: lambda})
	if err != nil {
		return nil, err
	}

	path := fmt.Sprintf(EndpointIssuerWallConflicts, url.PathEscape(issuer))

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+path, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}

	req.Header.Set("Content-Type", "application/json")

	resp, err := c.http.Do(req)
	if err != nil {
		return nil, fmt.Errorf("context-service request failed: %w", err)
	}

	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("context-service returned status %d", resp.StatusCode)
	}

	var result WallCheckResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("decoding context-service response: %w", err)
	}

	return result.Conflicts, nil
}
