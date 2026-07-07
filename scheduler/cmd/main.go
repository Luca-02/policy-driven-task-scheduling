package main

import (
	"os"

	"k8s.io/component-base/cli"
	_ "k8s.io/component-base/logs/json/register"
	_ "k8s.io/component-base/metrics/prometheus/clientgo"
	_ "k8s.io/component-base/metrics/prometheus/version"
	"k8s.io/kubernetes/cmd/kube-scheduler/app"

	"github.com/Luca-02/policy-driven-task-scheduling/scheduler/internal/registry"
)

func main() {
	command := app.NewSchedulerCommand(registry.Options()...)
	code := cli.Run(command)
	os.Exit(code)
}
