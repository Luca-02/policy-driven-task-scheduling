go mod init unimi.it/policy-driven-task-scheduling/scheduler-plugin

curl -o go.mod https://raw.githubusercontent.com/kubernetes-sigs/scheduler-plugins/release-1.34/go.mod

go mod edit -module unimi.it/policy-driven-task-scheduling/scheduler-plugin

<!-- TODO -->