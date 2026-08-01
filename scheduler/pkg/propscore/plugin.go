package propscore

import (
	"context"
	"encoding/json"
	"fmt"
	"strconv"
	"strings"

	v1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/klog/v2"
	fwk "k8s.io/kube-scheduler/framework"
	"k8s.io/kubernetes/pkg/scheduler/framework"

	"github.com/Luca-02/policy-driven-task-scheduling/scheduler/internal/config"
	"github.com/Luca-02/policy-driven-task-scheduling/scheduler/internal/nodeproperties"
)

const (
	Name = "PropScore"
)

type PropScore struct {
	cfg        config.Config
	logger     klog.Logger
	properties nodeproperties.Reader
}

var _ framework.ScorePlugin = &PropScore{}

func (p *PropScore) Name() string {
	return Name
}

func New(ctx context.Context, _ runtime.Object, _ framework.Handle) (framework.Plugin, error) {
	logger := klog.FromContext(ctx).WithValues("plugin", Name)
	cfg := config.Load()

	cache, err := nodeproperties.NewCache(ctx, cfg)
	if err != nil {
		logger.Error(err, "failed to initialise NodeProperty cache")
		return nil, fmt.Errorf("initialising NodeProperty cache: %w", err)
	}

	logger.V(2).Info("plugin initialised")
	return &PropScore{cfg: cfg, logger: logger, properties: cache}, nil
}

// Score computes phi_prop(n,t) for the candidate node. Unlike TransferScore,
// PropScore does not implement PreScore: the NodeProperty cache is kept
// continuously up to date in the background by its informer, so there is
// nothing to prepare per scheduling cycle.
func (p *PropScore) Score(ctx context.Context, _ fwk.CycleState, pod *v1.Pod, nodeInfo fwk.NodeInfo) (int64, *fwk.Status) {
	podName := pod.Name
	nodeName := nodeInfo.Node().Name
	logger := klog.FromContext(klog.NewContext(ctx, p.logger)).WithValues(
		"ExtensionPoint", "Score", "node", nodeName, "pod", podName)

	logger.V(4).Info("Starting score computation", "node", nodeName, "pod", podName)

	betaStarAnnotationKey := p.cfg.TaskPodAnnotationPrefix + "/" + p.cfg.BetaStarAnnotation

	betaStar, err := readBetaStar(pod, betaStarAnnotationKey)
	if err != nil {
		logger.Error(err, "beta-star annotation malformed", "betaStarAnnotationKey", betaStarAnnotationKey)
		return 0, fwk.AsStatus(fmt.Errorf("beta-star annotation malformed: %w", err))
	}
	logger.V(4).Info("beta-star read", "betaStar", betaStar)

	nodePropertiesLevel := readNodePropertiesLevel(nodeInfo.Node().Labels, p.cfg.NodePropertyLabelPrefix)
	logger.V(4).Info("node properties read", "nodePropertiesLevel", nodePropertiesLevel)

	phi := computePhiProp(betaStar, nodePropertiesLevel, p.properties)
	score := FromPhi(phi)
	logger.V(2).Info("phi_prop computed", "phi", phi, "score", score)

	logger.V(4).Info("Score computation completed", "node", nodeName, "pod", podName)

	return score, nil
}

// We do not normalize against the observed max: phi_prop is already in
// [0,1], and the [0, framework.MaxNodeScore] mapping preserves its
// absolute meaning.
func (p *PropScore) ScoreExtensions() framework.ScoreExtensions {
	return nil
}

// readBetaStar parses beta*(t) from the Pod's beta-star annotation. A
// missing annotation is not an error: it means the task has no property
// requirements, and computePhiProp naturally returns phi=1 for a nil map.
func readBetaStar(pod *v1.Pod, betaStarAnnotationKey string) (map[string]int, error) {
	raw, ok := pod.Annotations[betaStarAnnotationKey]
	if !ok {
		return nil, nil
	}

	var betaStar map[string]int
	if err := json.Unmarshal([]byte(raw), &betaStar); err != nil {
		return nil, err
	}

	return betaStar, nil
}

// readNodePropertiesLevel extracts alpha_p(n) for every property label present on
// the node. Properties without a label simply do not appear in the map;
// computePhiProp treats a missing entry as level 0.
func readNodePropertiesLevel(labels map[string]string, nodePropertyLabelPrefix string) map[string]int {
	levels := make(map[string]int)
	for k, v := range labels {
		if !strings.HasPrefix(k, nodePropertyLabelPrefix) {
			continue
		}

		prop := strings.TrimPrefix(k, nodePropertyLabelPrefix)
		prop = strings.TrimPrefix(prop, "/")
		if lvl, err := strconv.Atoi(v); err == nil {
			levels[prop] = lvl
		}
	}
	return levels
}
