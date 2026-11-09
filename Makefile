# Set PROVIDER=kind on `make up` to use kind. The default is k3d.
# The other commands find the running cluster themselves.

.DEFAULT_GOAL := help
.PHONY: help check up lab1 lab2 lab3 lab4 lab6 investigate compare status tutorial down

help: ## Show the available commands
	@awk 'BEGIN {FS = ":.*## "} /^[a-z0-9]+:.*## / {printf "  make %-10s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

check: ## Check the prerequisites
	@scripts/check-prereqs.sh

up: ## Create the cluster and deploy SigNoz and Lab 1 (safe to rerun)
	@scripts/up.sh

lab1: ## Rebuild and redeploy Lab 1
	@scripts/deploy-lab.sh 1

lab2: ## Deploy Lab 2, or redeploy it after a code change
	@scripts/deploy-lab.sh 2

lab3: ## Deploy Lab 3 and its extra scrape jobs
	@scripts/deploy-lab.sh 3

lab4: ## Deploy Lab 4: alert rules and a place to receive them
	@scripts/deploy-alerts.sh

lab6: ## Deploy Lab 6: SigNoz's MCP server and read-only access for AI agents
	@scripts/deploy-ai.sh

investigate: ## Investigate alerts with your own AI agent. HARNESS=claude, opencode or codex
	@python3 scripts/investigate_alerts.py $(or $(HARNESS),claude)

compare: ## Show what SigNoz captures from each lab
	@python3 scripts/compare_labs.py

status: ## Show nodes, pods and URLs
	@scripts/status.sh

tutorial: ## Run the interactive tutorial
	@python3 tutorial/server.py

down: ## Delete the cluster and all its data
	@scripts/down.sh
