# Set PROVIDER=kind on `make up` to use kind. The default is k3d.
# The other commands find the running cluster themselves.

.DEFAULT_GOAL := help
.PHONY: help check up status app tutorial down

help: ## Show the available commands
	@awk 'BEGIN {FS = ":.*## "} /^[a-z]+:.*## / {printf "  make %-10s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

check: ## Check the prerequisites
	@scripts/check-prereqs.sh

up: ## Create the cluster and deploy everything (safe to rerun)
	@scripts/up.sh

status: ## Show nodes, pods and URLs
	@scripts/status.sh

app: ## Rebuild and redeploy the test app after a code change
	@scripts/deploy-app.sh

tutorial: ## Run the interactive tutorial
	@python3 tutorial/server.py

down: ## Delete the cluster and all its data
	@scripts/down.sh
