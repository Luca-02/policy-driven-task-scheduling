package main

import (
	"context"
	"flag"
	"fmt"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"

	"github.com/policy-driven-task-scheduling/node-property-controller/internal/config"
	controllerpkg "github.com/policy-driven-task-scheduling/node-property-controller/internal/controller"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/util/rand"
	"k8s.io/client-go/dynamic"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
	"k8s.io/client-go/tools/clientcmd"
	"k8s.io/client-go/tools/leaderelection"
	"k8s.io/client-go/tools/leaderelection/resourcelock"
	"k8s.io/klog/v2"
)

func main() {
	klog.InitFlags(nil)
	local := flag.Bool("local", false, "run against the current kubeconfig with leader election disabled")
	kubeconfig := flag.String("kubeconfig", "", "path to kubeconfig; defaults to $KUBECONFIG or ~/.kube/config outside the cluster")
	flag.Parse()

	cfg := config.FromEnv()
	if *local {
		cfg.LeaderElection = false
	}

	rootCtx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	go runHealthServer(rootCtx, cfg.HealthAddr)

	restConfig, err := buildKubeConfig(*kubeconfig)
	if err != nil {
		klog.Fatalf("cannot build Kubernetes config: %v", err)
	}
	kubeClient, err := kubernetes.NewForConfig(restConfig)
	if err != nil {
		klog.Fatalf("cannot build Kubernetes client: %v", err)
	}
	dynamicClient, err := dynamic.NewForConfig(restConfig)
	if err != nil {
		klog.Fatalf("cannot build dynamic Kubernetes client: %v", err)
	}

	run := func(ctx context.Context) {
		reconciler := controllerpkg.NewReconciler(cfg, kubeClient, dynamicClient)
		if err := reconciler.Run(ctx); err != nil && ctx.Err() == nil {
			klog.Fatalf("controller stopped: %v", err)
		}
	}

	if !cfg.LeaderElection {
		klog.Infof("leader election disabled; starting active controller")
		run(rootCtx)
		return
	}

	identity, err := identity()
	if err != nil {
		klog.Fatalf("cannot build leader election identity: %v", err)
	}
	lock := &resourcelock.LeaseLock{
		LeaseMeta: metav1.ObjectMeta{Name: cfg.LeaderElectionID, Namespace: cfg.LeaderElectionNS},
		Client:    kubeClient.CoordinationV1(),
		LockConfig: resourcelock.ResourceLockConfig{
			Identity: identity,
		},
	}

	klog.Infof("starting leader election with lease %s/%s and identity %s", cfg.LeaderElectionNS, cfg.LeaderElectionID, identity)
	leaderelection.RunOrDie(rootCtx, leaderelection.LeaderElectionConfig{
		Lock:            lock,
		ReleaseOnCancel: true,
		LeaseDuration:   15 * time.Second,
		RenewDeadline:   10 * time.Second,
		RetryPeriod:     2 * time.Second,
		Callbacks: leaderelection.LeaderCallbacks{
			OnStartedLeading: run,
			OnStoppedLeading: func() { klog.Infof("lost leader election") },
			OnNewLeader: func(currentID string) {
				if currentID == identity {
					klog.Infof("acquired leadership")
					return
				}
				klog.Infof("current leader is %s", currentID)
			},
		},
	})
}

func buildKubeConfig(kubeconfig string) (*rest.Config, error) {
	if kubeconfig != "" {
		return clientcmd.BuildConfigFromFlags("", kubeconfig)
	}
	if config, err := rest.InClusterConfig(); err == nil {
		klog.Infof("loaded in-cluster Kubernetes configuration")
		return config, nil
	}
	if kubeconfig = os.Getenv("KUBECONFIG"); kubeconfig != "" {
		klog.Infof("loaded local Kubernetes configuration from KUBECONFIG")
		return clientcmd.BuildConfigFromFlags("", kubeconfig)
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return nil, err
	}
	defaultPath := filepath.Join(home, ".kube", "config")
	klog.Infof("loaded local Kubernetes configuration from %s", defaultPath)
	return clientcmd.BuildConfigFromFlags("", defaultPath)
}

func identity() (string, error) {
	hostname, err := os.Hostname()
	if err != nil {
		return "", err
	}
	return fmt.Sprintf("%s_%s", hostname, rand.String(8)), nil
}

func runHealthServer(ctx context.Context, addr string) {
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok\n"))
	})
	server := &http.Server{Addr: addr, Handler: mux, ReadHeaderTimeout: 5 * time.Second}

	go func() {
		<-ctx.Done()
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdownCtx)
	}()

	if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		klog.Fatalf("health server failed: %v", err)
	}
}
