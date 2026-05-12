k8s-init: 
	bash ./scripts/k8s-init.sh

k8s-token:
	@echo "Use the following token to log in to the Headlamp dashboard:"
	@kubectl create token headlamp-admin -n kube-system

k8s-dashboard:
	@echo "Starting Kubernetes dashboard..."
	@echo "Use the following token to log in to the Headlamp dashboard:"
	@kubectl create token headlamp-admin -n kube-system
	@echo
	@echo "You can access the dashboard at http://localhost:8080 after port forwarding."
	@kubectl port-forward -n kube-system service/headlamp 8080:80

k8s-start:
	@echo "Starting cluster containers..."
	@docker ps -aq --filter "name=thesis-" | xargs -r docker start

k8s-stop:
	@echo "Stopping cluster containers..."
	@docker ps -aq --filter "name=thesis-" | xargs -r docker stop

k8s-delete:
	@echo "Deleting cluster..."
	@kind delete clusters thesis