package v1alpha1

import (
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime/schema"
)

const (
	GroupName = "policydriven.unimi.it"
	Version   = "v1alpha1"
	Resource  = "nodeproperties"
	Kind      = "NodeProperty"
)

var (
	SchemeGroupVersion   = schema.GroupVersion{Group: GroupName, Version: Version}
	GroupVersionResource = schema.GroupVersionResource{
		Group:    GroupName,
		Version:  Version,
		Resource: Resource,
	}
)

type NodeProperty struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`
	Spec              NodePropertySpec `json:"spec,omitempty"`
}

type NodePropertySpec struct {
	Levels []LevelSpec `json:"levels"`
}

type LevelSpec struct {
	Level       int               `json:"level"`
	Disjunction []DisjunctionSpec `json:"disjunction"`
}

type DisjunctionSpec struct {
	Clause []ConditionSpec `json:"clause"`
}

type ConditionSpec struct {
	Key      string   `json:"key"`
	Operator string   `json:"operator"`
	Values   []string `json:"values,omitempty"`
}
