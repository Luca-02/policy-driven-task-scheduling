package nodeproperty

import (
	"context"
	"fmt"
	"sync"
	"time"

	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/client-go/dynamic"
	"k8s.io/client-go/dynamic/dynamicinformer"
	"k8s.io/client-go/rest"
	"k8s.io/client-go/tools/cache"
	"k8s.io/client-go/tools/clientcmd"
	"k8s.io/klog/v2"

	"github.com/Luca-02/policy-driven-task-scheduling/scheduler/internal/config"
)

const resyncPeriod = 10 * time.Minute

// Cache maintains an up-to-date, in-memory view of NodeProperty custom resources.
type Cache struct {
	mu    sync.RWMutex
	items map[string]NodePropertyInfo
}

var _ Reader = &Cache{}

// gvrFrom builds the NodeProperty GroupVersionResource from the shared
// scheduler configuration, so group/version/plural are configurable via the
// same env vars/defaults as the rest of the scheduler.
func gvrFrom(cfg config.Config) schema.GroupVersionResource {
	return schema.GroupVersionResource{
		Group:    cfg.CrdGroup,
		Version:  cfg.CrdVersion,
		Resource: cfg.NodePropertyResourcePlural,
	}
}

// NewCache builds a dynamic client from the scheduler's in-cluster
// credentials, then starts and syncs a NodeProperty informer against it.
func NewCache(ctx context.Context, cfg config.Config) (*Cache, error) {
	restCfg, err := rest.InClusterConfig()
	if err != nil {
		// Fall back to kubeconfig
		loadingRules := clientcmd.NewDefaultClientConfigLoadingRules()
		configOverrides := &clientcmd.ConfigOverrides{}
		kubeConfig := clientcmd.NewNonInteractiveDeferredLoadingClientConfig(loadingRules, configOverrides)
		restCfg, err = kubeConfig.ClientConfig()
		if err != nil {
			return nil, fmt.Errorf("loading in-cluster config: %w", err)
		}
	}

	dynClient, err := dynamic.NewForConfig(restCfg)
	if err != nil {
		return nil, fmt.Errorf("building dynamic client: %w", err)
	}

	return newCacheFromClient(ctx, cfg, dynClient)
}

// newCacheFromClient builds the cache from an already-constructed dynamic client.
func newCacheFromClient(ctx context.Context, cfg config.Config, dynClient dynamic.Interface) (*Cache, error) {
	logger := klog.FromContext(ctx).WithValues("component", cfg.NodePropertyResourcePlural+"-cache")

	gvr := gvrFrom(cfg)
	c := &Cache{items: make(map[string]NodePropertyInfo)}

	factory := dynamicinformer.NewDynamicSharedInformerFactory(dynClient, resyncPeriod)
	informer := factory.ForResource(gvr).Informer()

	_, err := informer.AddEventHandlerWithOptions(cache.ResourceEventHandlerFuncs{
		AddFunc:    c.upsert,
		DeleteFunc: c.delete,
		UpdateFunc: func(_, newObj any) { c.upsert(newObj) },
	}, cache.HandlerOptions{Logger: &logger})
	if err != nil {
		return nil, fmt.Errorf("registering event handler: %w", err)
	}

	go factory.Start(ctx.Done())
	if !cache.WaitForCacheSync(ctx.Done(), informer.HasSynced) {
		return nil, fmt.Errorf("failed to sync NodeProperty informer cache")
	}

	logger.Info("NodeProperty informer cache synced", "gvr", gvr, "properties", len(c.items))
	return c, nil
}

func (c *Cache) upsert(obj any) {
	u, ok := obj.(*unstructured.Unstructured)
	if !ok {
		return
	}
	info := extractInfo(u)
	c.mu.Lock()
	c.items[info.Name] = info
	c.mu.Unlock()
}

func (c *Cache) delete(obj any) {
	u, ok := obj.(*unstructured.Unstructured)
	if !ok {
		tombstone, isTombstone := obj.(cache.DeletedFinalStateUnknown)
		if !isTombstone {
			return
		}
		u, ok = tombstone.Obj.(*unstructured.Unstructured)
		if !ok {
			return
		}
	}
	c.mu.Lock()
	delete(c.items, u.GetName())
	c.mu.Unlock()
}

// Get returns the cached Info for a property name, and whether it was found.
func (c *Cache) Get(name string) (NodePropertyInfo, bool) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	info, ok := c.items[name]
	return info, ok
}

// extractInfo reads the necessary fields from a raw NodeProperty object.
//
// Weight defaults to 1 if omitted, matching the CRD's own OpenAPI default.
// MaxLevel is derived as the highest value in Levels.
func extractInfo(u *unstructured.Unstructured) NodePropertyInfo {
	info := NodePropertyInfo{
		Name:   u.GetName(),
		Weight: 1.0,
	}

	rawLevels, found, err := unstructured.NestedSlice(u.Object, "spec", "levels")
	if err != nil || !found {
		return info
	}

	for _, l := range rawLevels {
		m, ok := l.(map[string]any)
		if !ok {
			continue
		}

		lvl, found, err := unstructured.NestedInt64(m, "level")
		if err != nil || !found {
			continue
		}

		info.Levels = append(info.Levels, lvl)
		if lvl > info.MaxLevel {
			info.MaxLevel = lvl
		}
	}

	weight, found, err := unstructured.NestedFloat64(u.Object, "spec", "weight")
	if err == nil && found {
		info.Weight = weight
	}

	return info
}
