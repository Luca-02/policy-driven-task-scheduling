package controller

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"sync"
	"time"

	"github.com/policy-driven-task-scheduling/node-property-controller/internal/config"
	"github.com/policy-driven-task-scheduling/node-property-controller/internal/domain"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/apimachinery/pkg/util/runtime"
	"k8s.io/apimachinery/pkg/util/wait"
	"k8s.io/client-go/dynamic"
	"k8s.io/client-go/dynamic/dynamicinformer"
	"k8s.io/client-go/informers"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/tools/cache"
	"k8s.io/client-go/util/workqueue"
	"k8s.io/klog/v2"
)

const (
	kindNode     = "node"
	kindProperty = "property"
	kindDeleted  = "property-deleted"
)

var controlPlaneLabels = []string{
	"node-role.kubernetes.io/control-plane",
	"node-role.kubernetes.io/master",
}

type Reconciler struct {
	cfg config.Config

	kubeClient kubernetes.Interface
	gvr        schema.GroupVersionResource

	nodeInformer     cache.SharedIndexInformer
	propertyInformer cache.SharedIndexInformer
	queue            workqueue.TypedRateLimitingInterface[string]

	propertiesMu sync.RWMutex
	properties   map[string]domain.Property
}

func NewReconciler(cfg config.Config, kubeClient kubernetes.Interface, dynamicClient dynamic.Interface) *Reconciler {
	gvr := schema.GroupVersionResource{Group: cfg.Group, Version: cfg.Version, Resource: cfg.Plural}
	coreFactory := informers.NewSharedInformerFactory(kubeClient, cfg.ResyncPeriod)
	dynamicFactory := dynamicinformer.NewFilteredDynamicSharedInformerFactory(dynamicClient, cfg.ResyncPeriod, metav1.NamespaceAll, nil)

	reconciler := &Reconciler{
		cfg:              cfg,
		kubeClient:       kubeClient,
		gvr:              gvr,
		nodeInformer:     coreFactory.Core().V1().Nodes().Informer(),
		propertyInformer: dynamicFactory.ForResource(gvr).Informer(),
		queue:            workqueue.NewTypedRateLimitingQueue(workqueue.DefaultTypedControllerRateLimiter[string]()),
		properties:       map[string]domain.Property{},
	}

	reconciler.registerHandlers()
	return reconciler
}

func (r *Reconciler) Run(ctx context.Context) error {
	defer runtime.HandleCrash()
	defer r.queue.ShutDown()

	klog.Infof("starting informers for %s/%s/%s and nodes", r.cfg.Group, r.cfg.Version, r.cfg.Plural)
	go r.nodeInformer.Run(ctx.Done())
	go r.propertyInformer.Run(ctx.Done())

	if !cache.WaitForCacheSync(ctx.Done(), r.nodeInformer.HasSynced, r.propertyInformer.HasSynced) {
		return fmt.Errorf("timed out waiting for informer caches to sync")
	}

	r.loadPropertiesFromCache()
	r.enqueueAllNodes()

	for i := 0; i < r.cfg.ConcurrentWorkers; i++ {
		go wait.UntilWithContext(ctx, r.runWorker, time.Second)
	}

	<-ctx.Done()
	return nil
}

func (r *Reconciler) registerHandlers() {
	_, _ = r.nodeInformer.AddEventHandler(cache.ResourceEventHandlerFuncs{
		AddFunc: func(obj interface{}) { r.enqueueNode(obj) },
		UpdateFunc: func(_, newObj interface{}) {
			r.enqueueNode(newObj)
		},
		DeleteFunc: func(obj interface{}) { r.enqueueNodeDeleted(obj) },
	})

	_, _ = r.propertyInformer.AddEventHandler(cache.ResourceEventHandlerFuncs{
		AddFunc: func(obj interface{}) { r.enqueueProperty(obj) },
		UpdateFunc: func(_, newObj interface{}) {
			r.enqueueProperty(newObj)
		},
		DeleteFunc: func(obj interface{}) { r.enqueuePropertyDeleted(obj) },
	})
}

func (r *Reconciler) runWorker(ctx context.Context) {
	for r.processNextWorkItem(ctx) {
	}
}

func (r *Reconciler) processNextWorkItem(ctx context.Context) bool {
	key, shutdown := r.queue.Get()
	if shutdown {
		return false
	}
	defer r.queue.Done(key)

	if err := r.reconcile(ctx, key); err != nil {
		r.queue.AddRateLimited(key)
		klog.Errorf("reconcile %q failed: %v", key, err)
		return true
	}
	r.queue.Forget(key)
	return true
}

func (r *Reconciler) reconcile(ctx context.Context, key string) error {
	kind, name, ok := strings.Cut(key, "/")
	if !ok {
		return fmt.Errorf("invalid key %q", key)
	}

	switch kind {
	case kindNode:
		return r.reconcileNode(ctx, name)
	case kindProperty:
		return r.reconcileProperty(ctx, name)
	case kindDeleted:
		return r.reconcilePropertyDeleted(ctx, name)
	default:
		return fmt.Errorf("unknown key kind %q", kind)
	}
}

func (r *Reconciler) reconcileNode(ctx context.Context, name string) error {
	obj, exists, err := r.nodeInformer.GetStore().GetByKey(name)
	if err != nil || !exists {
		return err
	}
	node := obj.(*corev1.Node)
	if isControlPlaneNode(node.Labels) {
		klog.Infof("skipping control-plane node %q", node.Name)
		return nil
	}

	parsedNode := ParseNode(node.Name, node.Labels, r.cfg)
	currentLabels := node.Labels
	r.propertiesMu.RLock()
	properties := make(map[string]domain.Property, len(r.properties))
	for name, property := range r.properties {
		properties[name] = property
	}
	r.propertiesMu.RUnlock()

	for labelKey := range currentLabels {
		if strings.HasPrefix(labelKey, r.cfg.PropertyPrefix+"/") {
			propertyName := strings.TrimPrefix(labelKey, r.cfg.PropertyPrefix+"/")
			if _, known := properties[propertyName]; !known {
				if err := r.patchNodeLevel(ctx, node.Name, labelKey, nil, currentLabels[labelKey], true); err != nil {
					return err
				}
			}
		}
	}

	for _, property := range properties {
		level, err := parsedNode.EvaluateProperty(property)
		if err != nil {
			klog.Errorf("node %q property %q evaluation failed: %v", node.Name, property.Name, err)
			continue
		}
		labelKey := r.cfg.PropertyPrefix + "/" + property.Name
		current, exists := currentLabels[labelKey]
		if err := r.patchNodeLevel(ctx, node.Name, labelKey, &level, current, exists); err != nil {
			return err
		}
	}
	return nil
}

func (r *Reconciler) reconcileProperty(ctx context.Context, name string) error {
	obj, exists, err := r.propertyInformer.GetStore().GetByKey(name)
	if err != nil {
		return err
	}
	if !exists {
		return r.reconcilePropertyDeleted(ctx, name)
	}
	unstructuredObj := obj.(*unstructured.Unstructured)
	property, err := ParseProperty(name, unstructuredObj)
	if err != nil {
		klog.Errorf("property %q has invalid spec, skipping: %v", name, err)
		return nil
	}

	r.propertiesMu.Lock()
	r.properties[name] = property
	r.propertiesMu.Unlock()
	klog.Infof("property %q loaded with %d levels", name, len(property.Levels))

	return r.evaluatePropertyForAllNodes(ctx, property)
}

func (r *Reconciler) reconcilePropertyDeleted(ctx context.Context, name string) error {
	r.propertiesMu.Lock()
	delete(r.properties, name)
	r.propertiesMu.Unlock()
	labelKey := r.cfg.PropertyPrefix + "/" + name
	klog.Infof("property %q removed, cleaning node label %q", name, labelKey)

	for _, obj := range r.nodeInformer.GetStore().List() {
		node := obj.(*corev1.Node)
		if isControlPlaneNode(node.Labels) {
			continue
		}
		current, exists := node.Labels[labelKey]
		if err := r.patchNodeLevel(ctx, node.Name, labelKey, nil, current, exists); err != nil {
			return err
		}
	}
	return nil
}

func (r *Reconciler) evaluatePropertyForAllNodes(ctx context.Context, property domain.Property) error {
	labelKey := r.cfg.PropertyPrefix + "/" + property.Name
	for _, obj := range r.nodeInformer.GetStore().List() {
		node := obj.(*corev1.Node)
		if isControlPlaneNode(node.Labels) {
			continue
		}
		parsedNode := ParseNode(node.Name, node.Labels, r.cfg)
		level, err := parsedNode.EvaluateProperty(property)
		if err != nil {
			klog.Errorf("node %q property %q evaluation failed: %v", node.Name, property.Name, err)
			continue
		}
		current, exists := node.Labels[labelKey]
		if err := r.patchNodeLevel(ctx, node.Name, labelKey, &level, current, exists); err != nil {
			return err
		}
	}
	return nil
}

func (r *Reconciler) patchNodeLevel(ctx context.Context, nodeName, labelKey string, level *int, current string, currentExists bool) error {
	var desired *string
	if level != nil && *level > 0 {
		value := fmt.Sprintf("%d", *level)
		desired = &value
	}
	if desired != nil && current == *desired {
		return nil
	}
	if desired == nil && !currentExists {
		return nil
	}

	patch := struct {
		Metadata struct {
			Labels map[string]*string `json:"labels"`
		} `json:"metadata"`
	}{}
	patch.Metadata.Labels = map[string]*string{labelKey: desired}
	data, err := json.Marshal(patch)
	if err != nil {
		return err
	}

	_, err = r.kubeClient.CoreV1().Nodes().Patch(ctx, nodeName, types.StrategicMergePatchType, data, metav1.PatchOptions{})
	if apierrors.IsNotFound(err) {
		return nil
	}
	if err != nil {
		return err
	}
	if desired == nil {
		klog.Infof("node %q label %q removed", nodeName, labelKey)
	} else {
		klog.Infof("node %q label %q set to %q", nodeName, labelKey, *desired)
	}
	return nil
}

func (r *Reconciler) loadPropertiesFromCache() {
	loaded := map[string]domain.Property{}
	for _, obj := range r.propertyInformer.GetStore().List() {
		propertyObj := obj.(*unstructured.Unstructured)
		property, err := ParseProperty(propertyObj.GetName(), propertyObj)
		if err != nil {
			klog.Errorf("property %q has invalid spec during cache bootstrap: %v", propertyObj.GetName(), err)
			continue
		}
		loaded[property.Name] = property
	}
	r.propertiesMu.Lock()
	r.properties = loaded
	r.propertiesMu.Unlock()
	klog.Infof("bootstrapped %d node properties from informer cache", len(loaded))
}

func (r *Reconciler) enqueueAllNodes() {
	for _, obj := range r.nodeInformer.GetStore().List() {
		r.enqueueNode(obj)
	}
}

func (r *Reconciler) enqueueNode(obj interface{}) {
	node, ok := obj.(*corev1.Node)
	if !ok {
		return
	}
	r.queue.Add(kindNode + "/" + node.Name)
}

func (r *Reconciler) enqueueNodeDeleted(obj interface{}) {
	deleted, ok := obj.(cache.DeletedFinalStateUnknown)
	if ok {
		obj = deleted.Obj
	}
	node, ok := obj.(*corev1.Node)
	if ok {
		klog.Infof("node %q removed from informer cache", node.Name)
	}
}

func (r *Reconciler) enqueueProperty(obj interface{}) {
	property, ok := obj.(*unstructured.Unstructured)
	if !ok {
		return
	}
	r.queue.Add(kindProperty + "/" + property.GetName())
}

func (r *Reconciler) enqueuePropertyDeleted(obj interface{}) {
	deleted, ok := obj.(cache.DeletedFinalStateUnknown)
	if ok {
		obj = deleted.Obj
	}
	property, ok := obj.(*unstructured.Unstructured)
	if !ok {
		return
	}
	r.queue.Add(kindDeleted + "/" + property.GetName())
}

func isControlPlaneNode(labels map[string]string) bool {
	for _, label := range controlPlaneLabels {
		if _, ok := labels[label]; ok {
			return true
		}
	}
	return false
}
