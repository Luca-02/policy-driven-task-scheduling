package config

import (
	"os"
)

const (
	DefaultCrdGroup                   = "policydriven.unimi.it"
	DefaultCrdVersion                 = "v1alpha1"
	DefaultNodePropertyResourcePlural = "nodeproperties"
	DefaultDatasetServiceURL          = "https://dataset-service:8443"
	DefaultNodePropertyLabelPrefix    = "property.node.policydriven.unimi.it/"
	DefaultDatasetsAnnotationKey      = "scheduling.task.policydriven.unimi.it/datasets"
	DefaultBetaStarAnnotationKey      = "scheduling.task.policydriven.unimi.it/beta-star"
)

type Config struct {
	CrdGroup                   string
	CrdVersion                 string
	NodePropertyResourcePlural string
	DatasetServiceURL          string
	DatasetServiceCAFile       string

	// Key of the annotation carrying beta*(t), inherited by the Pod.
	NodePropertyLabelPrefix string

	// Key of the annotation carrying req(t), inherited by the Pod.
	DatasetsAnnotationKey string

	// Prefix of the node labels carrying alpha_p(n), one label per property.
	BetaStarAnnotationKey string
}

func getEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}

func Load() Config {
	cfg := Config{
		CrdGroup:                   getEnv("CRD_GROUP", DefaultCrdGroup),
		CrdVersion:                 getEnv("CRD_VERSION", DefaultCrdVersion),
		NodePropertyResourcePlural: getEnv("NODE_PROPERTY_RESOURCE_PLURAL", DefaultNodePropertyResourcePlural),
		DatasetServiceURL:          getEnv("DATASET_SERVICE_URL", DefaultDatasetServiceURL),
		DatasetServiceCAFile:       getEnv("DATASET_SERVICE_CA_FILE", ""),
		NodePropertyLabelPrefix:    getEnv("NODE_PROPERTY_LABEL_PREFIX", DefaultNodePropertyLabelPrefix),
		DatasetsAnnotationKey:      getEnv("DATASETS_ANNOTATION_KEY", DefaultDatasetsAnnotationKey),
		BetaStarAnnotationKey:      getEnv("BETA_STAR_ANNOTATION_KEY", DefaultBetaStarAnnotationKey),
	}

	return cfg
}
