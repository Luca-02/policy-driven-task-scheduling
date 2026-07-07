// Package registry centralizes the list of out-of-tree scheduler plugins
// enabled in this custom scheduler binary. cmd/main.go imports only this
// package, so enabling or disabling a plugin never requires touching main.go.
package registry

import (
	"k8s.io/kubernetes/cmd/kube-scheduler/app"

	"github.com/Luca-02/policy-driven-task-scheduling/scheduler/pkg/transferscore"
)

// Options returns the app.Option list registering every plugin implemented
// in this module. Pass it to app.NewSchedulerCommand in cmd/main.go, e.g.:
//
//	command := app.NewSchedulerCommand(registry.Options()...)
//
// Registering a plugin here only makes it available to the scheduler binary;
// it still needs to be enabled (and given a weight if it supports one) in the
// scheduler profile's pluginConfig/plugins section (scheduler-config.yaml).
func Options() []app.Option {
	return []app.Option{
		app.WithPlugin(transferscore.Name, transferscore.New),
		// app.WithPlugin(propscore.Name, propscore.New),
	}
}
