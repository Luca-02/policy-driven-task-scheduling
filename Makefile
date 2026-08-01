CLUSTER_NAME ?= kind
CLUSTER_CONFIG_FILE ?= examples/cluster-config.yaml
DATASET_SERVICE_LIGHT_MODE ?= true
CONTEXT_SERVICE_LIGHT_MODE ?= true

init: 
	CLUSTER_NAME=$(CLUSTER_NAME) \
		CLUSTER_CONFIG_FILE=$(CLUSTER_CONFIG_FILE) \
		DATASET_SERVICE_LIGHT_MODE=$(DATASET_SERVICE_LIGHT_MODE) \
		CONTEXT_SERVICE_LIGHT_MODE=$(CONTEXT_SERVICE_LIGHT_MODE) \
		bash ./scripts/init-cluster.sh

start:
	@echo "Starting cluster containers..."
	@docker ps -aq --filter "name=$(CLUSTER_NAME)-" | xargs -r docker start

stop:
	@echo "Stopping cluster containers..."
	@docker ps -aq --filter "name=$(CLUSTER_NAME)-" | xargs -r docker stop

delete:
	@echo "Deleting cluster..."
	@kind delete clusters $(CLUSTER_NAME)

dashboard:
	@echo "Starting Kubernetes dashboard..."
	@echo "Use the following token to log in to the Headlamp dashboard:"
	@kubectl create token headlamp-admin -n kube-system
	@echo
	@echo "You can access the dashboard at http://localhost:8080 after port forwarding."
	@kubectl port-forward -n kube-system svc/headlamp 8080:80

dashboard-token:
	@echo "Use the following token to log in to the Headlamp dashboard:"
	@kubectl create token headlamp-admin -n kube-system

loki: 
	@echo "Starting Loki stack..."
	@echo "Use the following credentials to log in to the Grafana dashboard:"
	@echo "Username: admin"
	@echo "Password: $(shell kubectl get secret --namespace loki loki-grafana -o jsonpath="{.data.admin-password}" | base64 --decode)"
	@echo
	@echo "You can access the Grafana dashboard at http://localhost:3000 after port forwarding."
	@kubectl port-forward -n loki svc/loki-grafana 3000:80
