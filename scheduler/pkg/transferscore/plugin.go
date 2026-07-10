package transferscore

import (
	"context"
	"encoding/json"
	"fmt"

	v1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/klog/v2"
	fwk "k8s.io/kube-scheduler/framework"
	"k8s.io/kubernetes/pkg/scheduler/framework"

	"github.com/Luca-02/policy-driven-task-scheduling/scheduler/internal/config"
	"github.com/Luca-02/policy-driven-task-scheduling/scheduler/internal/datasets"
)

const (
	Name = "TransferScore"

	preScoreStateKey fwk.StateKey = "preScoreState"
)

type TransferScore struct {
	cfg    config.Config
	logger klog.Logger
	client datasets.DatasetQuerier
}

var (
	_ framework.PreScorePlugin = &TransferScore{}
	_ framework.ScorePlugin    = &TransferScore{}
)

func (t *TransferScore) Name() string {
	return Name
}

func New(ctx context.Context, _ runtime.Object, _ framework.Handle) (framework.Plugin, error) {
	logger := klog.FromContext(ctx).WithValues("plugin", Name)
	cfg := config.Load()

	client, err := datasets.NewDatasetClient(cfg.DatasetServiceURL, cfg.DatasetServiceCAFile)
	if err != nil {
		logger.Error(err, "failed to initialise dataset-service client",
			"url", cfg.DatasetServiceURL, "caFile", cfg.DatasetServiceCAFile)
		return nil, fmt.Errorf("initialising dataset client: %w", err)
	}

	logger.V(2).Info("plugin initialised")
	return &TransferScore{cfg: cfg, logger: logger, client: client}, nil
}

// PreScore makes one call to the dataset-service for all datasets in req(t)
// and stores their info in the cycle state, so Score does not per-node I/O.
func (t *TransferScore) PreScore(ctx context.Context, state fwk.CycleState, pod *v1.Pod, nodes []fwk.NodeInfo) *fwk.Status {
	logger := klog.FromContext(klog.NewContext(ctx, t.logger)).WithValues("ExtensionPoint", "PreScore", "pod", pod.Name)

	raw, ok := pod.Annotations[t.cfg.DatasetsAnnotationKey]
	if !ok {
		logger.V(4).Info("no datasets annotation found, req(t) is empty")
		state.Write(preScoreStateKey, &preScoreState{})
		return nil
	}

	var datasets []string
	if err := json.Unmarshal([]byte(raw), &datasets); err != nil {
		logger.Error(err, "datasets annotation malformed", "raw", raw)
		return fwk.AsStatus(fmt.Errorf("datasets annotation malformed: %w", err))
	}

	if len(datasets) == 0 {
		logger.V(4).Info("datasets annotation is an empty list, req(t) is empty")
		state.Write(preScoreStateKey, &preScoreState{})
		return nil
	}

	logger.V(4).Info("fetching dataset info from dataset-service", "datasets", datasets)
	infos, err := t.client.Query(ctx, datasets)
	if err != nil {
		logger.Error(err, "failed to fetch dataset info", "datasets", datasets)
		return fwk.AsStatus(fmt.Errorf("fetching dataset info: %w", err))
	}

	transferState := buildPreScoreState(infos)
	logger.V(2).Info("PreScore state built", "state", transferState)

	state.Write(preScoreStateKey, transferState)
	return fwk.NewStatus(fwk.Success, "PreScore completed successfully")
}

func (t *TransferScore) Score(ctx context.Context, state fwk.CycleState, pod *v1.Pod, nodeInfo fwk.NodeInfo) (int64, *fwk.Status) {
	podName := pod.Name
	nodeName := nodeInfo.Node().Name
	logger := klog.FromContext(klog.NewContext(ctx, t.logger)).WithValues(
		"ExtensionPoint", "Score", "node", nodeName, "pod", podName)

	data, err := state.Read(preScoreStateKey)
	if err != nil {
		logger.Error(err, "failed to read transfer state")
		return 0, fwk.AsStatus(fmt.Errorf("reading transfer state: %w", err))
	}
	logger.V(4).Info("PreScore state read", "state", data)

	status, ok := data.(*preScoreState)
	if !ok {
		err := fmt.Errorf("unexpected transfer state type %T", data)
		logger.Error(err, "transfer state has unexpected type")
		return 0, fwk.AsStatus(err)
	}

	phi := computePhiTransfer(nodeName, status)
	score := FromPhi(phi)
	logger.V(2).Info("phi_transfer computed", "phi", phi, "score", score)

	return score, nil
}

// We do not normalize against the observed max: phi_transfer is already in [0,1],
// and the [0, framework.MaxNodeScore] mapping preserves its absolute meaning.
func (t *TransferScore) ScoreExtensions() framework.ScoreExtensions {
	return nil
}
