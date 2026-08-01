package config

import (
	"os"
)

const (
	DefaultGroup = "policydriven.unimi.it"

	DefaultCrdVersion                 = "v1alpha1"
	DefaultNodePropertyResourcePlural = "nodeproperties"

	DefaultDatasetServiceURL = "https://127.0.0.1:8443"
	DefaultContextServiceURL = "https://127.0.0.1:8443"

	DefaultTaskPodAnnotationPrefix   = "scheduling.task." + DefaultGroup
	DefaultNodePropertyLabelPrefix   = "property.node." + DefaultGroup
	DefaultNodeTraceAnnotationPrefix = "trace.node." + DefaultGroup

	DefaultDatasetsAnnotation = "datasets"
	DefaultBetaStarAnnotation = "betaStar"
	DefaultIssuerAnnotation   = "issuer"
	DefaultCtxStarAnnotation  = "ctxStar"
	DefaultContextsAnnotation = "contexts"
)

type Config struct {
	Group string

	CrdVersion                 string
	NodePropertyResourcePlural string

	DatasetServiceURL    string
	DatasetServiceCAFile string
	ContextServiceURL    string
	ContextServiceCAFile string

	TaskPodAnnotationPrefix   string
	NodePropertyLabelPrefix   string
	NodeTraceAnnotationPrefix string

	// Annotation carrying req(t), inherited by the Pod.
	DatasetsAnnotation string

	// Annotation carrying beta*(t), inherited by the Pod.
	BetaStarAnnotation string

	// Annotation carrying iss(t), inherited by the Pod.
	IssuerAnnotation string

	// Annotation carrying ctx*(t), inherited by the Pod.
	CtxStarAnnotation string

	// Annotation carrying Lambda(n), inherited by the Node.
	ContextsAnnotation string
}

func getEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}

func Load() Config {
	cfg := Config{
		Group:                      getEnv("GROUP", DefaultGroup),
		CrdVersion:                 getEnv("CRD_VERSION", DefaultCrdVersion),
		NodePropertyResourcePlural: getEnv("NODE_PROPERTY_RESOURCE_PLURAL", DefaultNodePropertyResourcePlural),

		DatasetServiceURL:    getEnv("DATASET_SERVICE_URL", DefaultDatasetServiceURL),
		DatasetServiceCAFile: getEnv("DATASET_SERVICE_CA_FILE", ""),
		ContextServiceURL:    getEnv("CONTEXT_SERVICE_URL", DefaultContextServiceURL),
		ContextServiceCAFile: getEnv("CONTEXT_SERVICE_CA_FILE", ""),

		TaskPodAnnotationPrefix:   getEnv("TASK_POD_ANNOTATION_PREFIX", DefaultTaskPodAnnotationPrefix),
		NodePropertyLabelPrefix:   getEnv("NODE_PROPERTY_LABEL_PREFIX", DefaultNodePropertyLabelPrefix),
		NodeTraceAnnotationPrefix: getEnv("NODE_TRACE_ANNOTATION_PREFIX", DefaultNodeTraceAnnotationPrefix),

		DatasetsAnnotation: getEnv("DATASETS_ANNOTATION_KEY", DefaultDatasetsAnnotation),
		BetaStarAnnotation: getEnv("BETA_STAR_ANNOTATION_KEY", DefaultBetaStarAnnotation),
		IssuerAnnotation:   getEnv("ISSUER_ANNOTATION_KEY", DefaultIssuerAnnotation),
		CtxStarAnnotation:  getEnv("CTX_STAR_ANNOTATION_KEY", DefaultCtxStarAnnotation),
		ContextsAnnotation: getEnv("CONTEXTS_ANNOTATION_KEY", DefaultContextsAnnotation),
	}

	return cfg
}
