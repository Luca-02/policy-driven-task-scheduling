package propscore

// import (
// 	"context"

// 	v1 "k8s.io/api/core/v1"
// 	"k8s.io/apimachinery/pkg/runtime"
// 	"k8s.io/klog/v2"
// 	fwk "k8s.io/kube-scheduler/framework"
// 	"k8s.io/kubernetes/pkg/scheduler/framework"
// )

// const (
// 	Name = "PropScore"

// 	preScoreStateKey fwk.StateKey = "preScoreState"
// )

// type PropScore struct {
// 	logger klog.Logger
// }

// var (
// 	_ framework.PreScorePlugin = &PropScore{}
// 	_ framework.ScorePlugin    = &PropScore{}
// )

// func (t *PropScore) Name() string {
// 	return Name
// }

// func New(ctx context.Context, _ runtime.Object, _ framework.Handle) (framework.Plugin, error) {
// 	logger := klog.FromContext(ctx).WithValues("plugin", Name)

// 	logger.Info("plugin initialised")
// 	return &PropScore{logger: logger}, nil
// }

// // PreScore makes one call to the dataset-service for all datasets in req(t)
// // and stores their info in the cycle state, so Score does not per-node I/O.
// func (t *PropScore) PreScore(ctx context.Context, state fwk.CycleState, pod *v1.Pod, nodes []fwk.NodeInfo) *fwk.Status {
// 	logger := klog.FromContext(klog.NewContext(ctx, t.logger)).WithValues("ExtensionPoint", "PreScore")

// 	return fwk.NewStatus(fwk.Success, "PreScore completed successfully")
// }

// func (t *PropScore) Score(ctx context.Context, state fwk.CycleState, pod *v1.Pod, nodeInfo fwk.NodeInfo) (int64, *fwk.Status) {
// 	podName := pod.Name
// 	nodeName := nodeInfo.Node().Name
// 	logger := klog.FromContext(klog.NewContext(ctx, t.logger)).WithValues(
// 		"ExtensionPoint", "Score", "node", nodeName, "pod", podName)

// 	return framework.MaxNodeScore, nil
// }

// // We do not normalize against the observed max: phi_transfer is already in [0,1],
// // and the [0, framework.MaxNodeScore] mapping preserves its absolute meaning.
// func (t *PropScore) ScoreExtensions() framework.ScoreExtensions { return nil }
