CLUSTER_NAME ?= kind

init: 
	CLUSTER_NAME=$(CLUSTER_NAME) bash ./scripts/init-cluster.sh

token:
	@echo "Use the following token to log in to the Headlamp dashboard:"
	@kubectl create token headlamp-admin -n kube-system

dashboard:
	@echo "Starting Kubernetes dashboard..."
	@echo "Use the following token to log in to the Headlamp dashboard:"
	@kubectl create token headlamp-admin -n kube-system
	@echo
	@echo "You can access the dashboard at http://localhost:8080 after port forwarding."
	@kubectl port-forward -n kube-system service/headlamp 8080:80

start:
	@echo "Starting cluster containers..."
	@docker ps -aq --filter "name=$(CLUSTER_NAME)-" | xargs -r docker start

stop:
	@echo "Stopping cluster containers..."
	@docker ps -aq --filter "name=$(CLUSTER_NAME)-" | xargs -r docker stop

delete:
	@echo "Deleting cluster..."
	@kind delete clusters $(CLUSTER_NAME)