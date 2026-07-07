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

	// Key of the annotation carrying req(t), inherited by the Pod.
	datasetsAnnotationKey = "scheduling.task.policydriven.unimi.it/datasets"
)

type TransferScore struct {
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
	logger := klog.FromContext(ctx).WithValues("scheduler", "plugin", Name)

	cfg, err := config.Load()
	if err != nil {
		logger.Error(err, "failed to load configuration")
		return nil, fmt.Errorf("loading configuration: %w", err)
	}

	client, err := datasets.NewDatasetClient(cfg.DatasetServiceURL, cfg.DatasetServiceCAFile)
	if err != nil {
		logger.Error(err, "failed to initialise dataset-service client",
			"url", cfg.DatasetServiceURL, "caFile", cfg.DatasetServiceCAFile)
		return nil, fmt.Errorf("initialising dataset client: %w", err)
	}

	logger.Info("plugin initialised")
	return &TransferScore{logger: logger, client: client}, nil
}

// PreScore makes one call to the dataset-service for all datasets in req(t)
// and stores their info in the cycle state, so Score does not per-node I/O.
func (t *TransferScore) PreScore(ctx context.Context, state fwk.CycleState, pod *v1.Pod, nodes []fwk.NodeInfo) *fwk.Status {
	raw, ok := pod.Annotations[datasetsAnnotationKey]
	if !ok {
		t.logger.Info("no datasets annotation found, req(t) is empty")
		state.Write(transferStateKey, &transferState{})
		return nil
	}

	var datasets []string
	if err := json.Unmarshal([]byte(raw), &datasets); err != nil {
		t.logger.Error(err, "datasets annotation malformed", "raw", raw)
		return fwk.AsStatus(fmt.Errorf("datasets annotation malformed: %w", err))
	}

	if len(datasets) == 0 {
		t.logger.Info("datasets annotation is an empty list, req(t) is empty")
		state.Write(transferStateKey, &transferState{})
		return nil
	}

	t.logger.Info("fetching dataset info from dataset-service", "datasets", datasets, "candidateNodes", len(nodes))

	infos, err := t.client.Query(ctx, datasets)
	if err != nil {
		t.logger.Error(err, "failed to fetch dataset info", "datasets", datasets)
		return fwk.AsStatus(fmt.Errorf("fetching dataset info: %w", err))
	}

	transferState := buildTransferState(infos)
	t.logger.Info("dataset info fetched", "datasets", len(transferState.datasets), "totalSizeMB", transferState.totalSizeMB)

	state.Write(transferStateKey, transferState)
	return nil
}

func (t *TransferScore) Score(_ context.Context, state fwk.CycleState, pod *v1.Pod, nodeInfo fwk.NodeInfo) (int64, *fwk.Status) {
	data, err := state.Read(transferStateKey)
	if err != nil {
		t.logger.Error(err, "failed to read transfer state")
		return 0, fwk.AsStatus(fmt.Errorf("reading transfer state: %w", err))
	}

	status, ok := data.(*transferState)
	if !ok {
		err := fmt.Errorf("unexpected transfer state type %T", data)
		t.logger.Error(err, "transfer state has unexpected type")
		return 0, fwk.AsStatus(err)
	}

	podName := pod.Name
	nodeName := nodeInfo.Node().Name

	phi := computeTransferPhi(nodeName, status)
	score := FromPhi(phi)
	t.logger.Info("phi_transfer computed", "podName", podName, "nodeName", nodeName, "phi", phi, "score", score)

	return score, nil
}

// We do not normalize against the observed max: phi_transfer is already in [0,1],
// and the [0, framework.MaxNodeScore] mapping preserves its absolute meaning.
func (t *TransferScore) ScoreExtensions() framework.ScoreExtensions { return nil }
