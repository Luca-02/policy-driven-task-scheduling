package config

import (
	"os"
	"strconv"
	"time"
)

type Config struct {
	Group             string
	Version           string
	Plural            string
	AttributePrefix   string
	PropertyPrefix    string
	LogLevel          string
	HealthAddr        string
	LeaderElection    bool
	LeaderElectionID  string
	LeaderElectionNS  string
	ResyncPeriod      time.Duration
	ConcurrentWorkers int
}

func FromEnv() Config {
	return Config{
		Group:             getenv("GROUP", "policydriven.unimi.it"),
		Version:           getenv("VERSION", "v1alpha1"),
		Plural:            getenv("PLURAL", "nodeproperties"),
		AttributePrefix:   getenv("ATTRIBUTE_PREFIX", "attribute.node.policydriven.unimi.it"),
		PropertyPrefix:    getenv("PROPERTY_PREFIX", "property.node.policydriven.unimi.it"),
		LogLevel:          getenv("LOG_LEVEL", "INFO"),
		HealthAddr:        getenv("HEALTH_ADDR", ":9090"),
		LeaderElection:    getenvBool("LEADER_ELECTION", true),
		LeaderElectionID:  getenv("LEADER_ELECTION_ID", "node-property-controller"),
		LeaderElectionNS:  getenv("LEADER_ELECTION_NAMESPACE", getenv("POD_NAMESPACE", "node-property-controller")),
		ResyncPeriod:      getenvDuration("RESYNC_PERIOD", 10*time.Hour),
		ConcurrentWorkers: getenvInt("CONCURRENT_WORKERS", 2),
	}
}

func getenv(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}

func getenvBool(key string, fallback bool) bool {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}
	parsed, err := strconv.ParseBool(value)
	if err != nil {
		return fallback
	}
	return parsed
}

func getenvInt(key string, fallback int) int {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}
	parsed, err := strconv.Atoi(value)
	if err != nil || parsed < 1 {
		return fallback
	}
	return parsed
}

func getenvDuration(key string, fallback time.Duration) time.Duration {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}
	parsed, err := time.ParseDuration(value)
	if err != nil {
		return fallback
	}
	return parsed
}
