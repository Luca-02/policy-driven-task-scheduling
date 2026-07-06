package transfer

import (
	"context"
	"encoding/json"
	"fmt"
	"os"

	v1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/runtime"
	fwk "k8s.io/kube-scheduler/framework"
	"k8s.io/kubernetes/pkg/scheduler/framework"
)

const (
	Name = "TransferScore"

	// Key of the annotation carrying req(t), inherited by the Pod (propagated by JobBuilder).
	datasetsAnnotationKey = "scheduling.task.policydriven.unimi.it/datasets"
)

type Transfer struct {
	client datasetQuerier
}

var (
	_ framework.PreScorePlugin = &Transfer{}
	_ framework.ScorePlugin    = &Transfer{}
)

func (t *Transfer) Name() string {
	return Name
}

func New(_ context.Context, _ runtime.Object, _ framework.Handle) (framework.Plugin, error) {
	client, err := NewDatasetClient(
		os.Getenv("DATASET_SERVICE_URL"),
		os.Getenv("DATASET_SERVICE_CA_FILE"),
	)
	if err != nil {
		return nil, fmt.Errorf("initialising dataset client: %w", err)
	}
	return &Transfer{client: client}, nil
}

// PreScore makes ONE call to the dataset-service for all datasets in req(t)
// and stores size/locality in the cycle state, so Score does no per-node I/O.
func (t *Transfer) PreScore(ctx context.Context, state fwk.CycleState, pod *v1.Pod, _ []fwk.NodeInfo) *fwk.Status {
	raw, ok := pod.Annotations[datasetsAnnotationKey]
	if !ok {
		state.Write(stateKey, &transferState{}) // req(t) empty -> phi=1 everywhere
		return nil
	}

	var keys []string
	if err := json.Unmarshal([]byte(raw), &keys); err != nil {
		return fwk.AsStatus(fmt.Errorf("datasets annotation malformed: %w", err))
	}

	if len(keys) == 0 {
		state.Write(stateKey, &transferState{})
		return nil
	}

	infos, err := t.client.Query(ctx, keys)
	if err != nil {
		return fwk.AsStatus(fmt.Errorf("fetching dataset info: %w", err))
	}

	state.Write(stateKey, buildTransferState(infos))
	return nil
}

func (t *Transfer) Score(_ context.Context, state fwk.CycleState, _ *v1.Pod, nodeInfo fwk.NodeInfo) (int64, *fwk.Status) {
	data, err := state.Read(stateKey)
	if err != nil {
		return 0, fwk.AsStatus(fmt.Errorf("reading transfer state: %w", err))
	}

	st, ok := data.(*transferState)
	if !ok {
		return 0, fwk.AsStatus(fmt.Errorf("unexpected transfer state type %T", data))
	}

	return computeTransferScore(nodeInfo.Node().Name, st), nil
}

// We do not normalize against the observed max: phi_transfer is already in
// [0,1], and the *100 mapping preserves its absolute meaning.
func (t *Transfer) ScoreExtensions() framework.ScoreExtensions { return nil }
