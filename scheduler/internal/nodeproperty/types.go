package nodeproperty

// NodePropertyInfo holds the information about a NodeProperty custom resource.
type NodePropertyInfo struct {
	Name     string
	Weight   float64
	MaxLevel int64
	Levels   []int64
}

// Reader abstracts read access to NodeProperty data.
type Reader interface {
	Get(name string) (NodePropertyInfo, bool)
}
