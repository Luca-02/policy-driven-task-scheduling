package config

import (
	"testing"
	"time"
)

func TestFromEnvDefaults(t *testing.T) {
	t.Setenv("ATTRIBUTE_PREFIX", "")
	t.Setenv("PROPERTY_PREFIX", "")
	t.Setenv("LEADER_ELECTION", "")
	t.Setenv("CONCURRENT_WORKERS", "")
	t.Setenv("RESYNC_PERIOD", "")

	cfg := FromEnv()
	if cfg.AttributePrefix != DefaultAttributePrefix {
		t.Fatalf("expected default attribute prefix %q, got %q", DefaultAttributePrefix, cfg.AttributePrefix)
	}
	if cfg.PropertyPrefix != DefaultPropertyPrefix {
		t.Fatalf("expected default property prefix %q, got %q", DefaultPropertyPrefix, cfg.PropertyPrefix)
	}
	if !cfg.LeaderElection {
		t.Fatal("expected leader election enabled by default")
	}
	if cfg.ConcurrentWorkers != 2 {
		t.Fatalf("expected 2 workers, got %d", cfg.ConcurrentWorkers)
	}
	if cfg.ResyncPeriod != 10*time.Hour {
		t.Fatalf("expected 10h resync, got %s", cfg.ResyncPeriod)
	}
}

func TestFromEnvOverrides(t *testing.T) {
	t.Setenv("ATTRIBUTE_PREFIX", "custom.attribute")
	t.Setenv("PROPERTY_PREFIX", "custom.property")
	t.Setenv("LEADER_ELECTION", "false")
	t.Setenv("CONCURRENT_WORKERS", "5")
	t.Setenv("RESYNC_PERIOD", "30m")
	t.Setenv("POD_NAMESPACE", "from-pod")

	cfg := FromEnv()
	if cfg.AttributePrefix != "custom.attribute" || cfg.PropertyPrefix != "custom.property" {
		t.Fatalf("unexpected prefixes: %#v", cfg)
	}
	if cfg.LeaderElection {
		t.Fatal("expected leader election disabled")
	}
	if cfg.ConcurrentWorkers != 5 {
		t.Fatalf("expected 5 workers, got %d", cfg.ConcurrentWorkers)
	}
	if cfg.ResyncPeriod != 30*time.Minute {
		t.Fatalf("expected 30m resync, got %s", cfg.ResyncPeriod)
	}
	if cfg.LeaderElectionNS != "from-pod" {
		t.Fatalf("expected namespace from POD_NAMESPACE, got %q", cfg.LeaderElectionNS)
	}
}

func TestFromEnvInvalidValuesFallBack(t *testing.T) {
	t.Setenv("LEADER_ELECTION", "not-bool")
	t.Setenv("CONCURRENT_WORKERS", "0")
	t.Setenv("RESYNC_PERIOD", "not-duration")

	cfg := FromEnv()
	if !cfg.LeaderElection {
		t.Fatal("invalid bool should fall back to true")
	}
	if cfg.ConcurrentWorkers != 2 {
		t.Fatalf("invalid workers should fall back to 2, got %d", cfg.ConcurrentWorkers)
	}
	if cfg.ResyncPeriod != 10*time.Hour {
		t.Fatalf("invalid resync should fall back to 10h, got %s", cfg.ResyncPeriod)
	}
}
