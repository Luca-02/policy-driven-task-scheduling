package wallfilter

import (
	"context"
	"fmt"

	v1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/client-go/kubernetes"
	"k8s.io/klog/v2"
	fwk "k8s.io/kube-scheduler/framework"
	"k8s.io/kubernetes/pkg/scheduler/framework"

	"github.com/Luca-02/policy-driven-task-scheduling/scheduler/internal/config"
	"github.com/Luca-02/policy-driven-task-scheduling/scheduler/internal/contexts"
	"github.com/Luca-02/policy-driven-task-scheduling/scheduler/internal/nodes"
)

const Name = "WallFilter"

type WallFilter struct {
	cfg       config.Config
	logger    klog.Logger
	client    contexts.WallChecker
	clientset kubernetes.Interface
}

var (
	_ framework.FilterPlugin   = &WallFilter{}
	_ framework.PostBindPlugin = &WallFilter{}
)

func (w *WallFilter) Name() string {
	return Name
}

func New(ctx context.Context, _ runtime.Object, fh framework.Handle) (framework.Plugin, error) {
	logger := klog.FromContext(ctx).WithValues("plugin", Name)
	cfg := config.Load()

	client, err := contexts.NewContextClient(cfg.ContextServiceURL, cfg.ContextServiceCAFile)
	if err != nil {
		logger.Error(err, "failed to initialise context-service client",
			"url", cfg.ContextServiceURL, "caFile", cfg.ContextServiceCAFile)
		return nil, fmt.Errorf("initialising context client: %w", err)
	}

	logger.V(2).Info("plugin initialised")
	return &WallFilter{cfg: cfg, logger: logger, client: client, clientset: fh.ClientSet()}, nil
}

// Filter implements c_wall. The actual decision lives in checkWall, which takes
// plain issuer/lambda values instead of framework types, so it can be unit tested
// without constructing a fwk.NodeInfo.
func (w *WallFilter) Filter(ctx context.Context, _ fwk.CycleState, pod *v1.Pod, nodeInfo fwk.NodeInfo) *fwk.Status {
	nodeName := nodeInfo.Node().Name
	logger := klog.FromContext(klog.NewContext(ctx, w.logger)).WithValues(
		"ExtensionPoint", "Filter", "node", nodeName, "pod", pod.Name)

	logger.V(4).Info("Starting filter computation", "node", nodeName, "pod", pod.Name)

	issuerAnnotationKey := w.cfg.TaskPodAnnotationPrefix + "/" + w.cfg.IssuerAnnotation
	lambdaAnnotationKey := w.cfg.NodeTraceAnnotationPrefix + "/" + w.cfg.ContextsAnnotation

	issuer := pod.Annotations[issuerAnnotationKey]
	lambda := nodes.Get(nodeInfo.Node(), lambdaAnnotationKey)
	logger.V(4).Info("Parsed Lambda(n)", "lambda", lambda)

	status := checkWall(ctx, w.client, issuer, lambda)

	switch {
	case status.Code() == fwk.Success:
		logger.V(2).Info("c_wall satisfied", "issuer", issuer, "lambda", lambda)
	case status.Code() == fwk.Unschedulable:
		logger.V(2).Info("c_wall violated", "issuer", issuer, "lambda", lambda, "reason", status.Message())
	default:
		logger.Error(status.AsError(), "failed to check c_wall conflicts", "issuer", issuer, "lambda", lambda)
	}

	logger.V(4).Info("Filter computation completed", "node", nodeName, "pod", pod.Name)

	return status
}

// PostBind deposits ctx*(t) onto Lambda(n) for the node actually
// selected by Bind, implementing:
//
//	f(t) != bot => Lambda(f(t)) <- Lambda(f(t)) union ctx*(t)
//
// The Scheduler Framework's PostBindPlugin contract has no return value:
// the bind has already happened by the time this runs, so an update
// failure here cannot roll it back or fail the scheduling cycle. It is
// logged and left to a later reconciliation (or to a subsequent task
// landing on the same node updating it again) rather than surfaced as
// an error.
func (w *WallFilter) PostBind(ctx context.Context, _ fwk.CycleState, pod *v1.Pod, nodeName string) {
	logger := klog.FromContext(klog.NewContext(ctx, w.logger)).WithValues(
		"ExtensionPoint", "PostBind", "node", nodeName, "pod", pod.Name)

	ctxStarAnnotationKey := w.cfg.TaskPodAnnotationPrefix + "/" + w.cfg.CtxStarAnnotation

	ctxStar, err := parseCtxStar(pod.Annotations[ctxStarAnnotationKey])
	if err != nil {
		logger.Error(err, "ctx-star annotation malformed, nothing deposited")
		return
	}

	if len(ctxStar) == 0 {
		logger.V(4).Info("ctx*(t) is empty, nothing to deposit")
		return
	}

	contextsAnnotationKey := w.cfg.NodeTraceAnnotationPrefix + "/" + w.cfg.ContextsAnnotation

	if err := nodes.Update(ctx, w.clientset, nodeName, contextsAnnotationKey, ctxStar); err != nil {
		logger.Error(err, "failed to update Lambda(n)", "ctxStar", ctxStar)
		return
	}

	logger.V(2).Info("Lambda(n) updated", "ctxStar", ctxStar)
}
