package config

import (
	"os"
)

const (
	DefaultDatasetServiceURL = "https://dataset-service:8443"
)

type Config struct {
	DatasetServiceURL    string
	DatasetServiceCAFile string
}

func getEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}

func Load() (*Config, error) {
	cfg := &Config{
		DatasetServiceURL:    getEnv("DATASET_SERVICE_URL", DefaultDatasetServiceURL),
		DatasetServiceCAFile: getEnv("DATASET_SERVICE_CA_FILE", ""),
	}

	return cfg, nil
}
