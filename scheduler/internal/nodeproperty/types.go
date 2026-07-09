package nodeproperty

// NodePropertyInfo holds the information about a NodeProperty custom resource.
type NodePropertyInfo struct {
	Name     string
	Weight   float64
	MaxLevel int
	Levels   []int
}

// Reader abstracts read access to NodeProperty data.
type Reader interface {
	Get(name string) (NodePropertyInfo, bool)
}
