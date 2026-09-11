package config

import (
	"os"
	"strconv"
	"time"
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

	// DefaultWallAssumedTTL bounds how long WallFilter keeps honouring a
	// Lambda(n) deposit that it decided in Reserve but has not yet observed in
	// a node snapshot. It only has to outlast informer propagation of the
	// PostBind write, which is on the order of tens to hundreds of
	// milliseconds under load, so seconds is a generous margin; too small
	// reopens the TOCTOU window, too large needlessly constrains scheduling
	// when a deposit failed to persist.
	DefaultWallAssumedTTL = 5 * time.Second
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

	// How long an assumed Lambda(n) deposit keeps constraining c_wall while it
	// is not yet visible in the node snapshots Filter reads.
	WallAssumedTTL time.Duration
}

func getEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}

// getEnvSeconds reads a whole number of seconds from the environment. A missing,
// empty or unparsable value falls back to the default, so a typo degrades to
// the safe built-in rather than to zero.
func getEnvSeconds(key string, defaultValue time.Duration) time.Duration {
	raw := os.Getenv(key)
	if raw == "" {
		return defaultValue
	}
	seconds, err := strconv.Atoi(raw)
	if err != nil || seconds < 0 {
		return defaultValue
	}
	return time.Duration(seconds) * time.Second
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

		WallAssumedTTL: getEnvSeconds("WALL_ASSUMED_TTL_SECONDS", DefaultWallAssumedTTL),
	}

	return cfg
}
