#!/usr/bin/env bash
# Deploys Lab 6's cluster side: SigNoz's MCP server, and read-only access for AI
# agents. The agent itself is the one on your machine. Safe to rerun.
source "$(dirname "$0")/lib.sh"
cd "$ROOT"

step "MCP server and read-only access"
k apply -f labs/lab6-ai/k8s/mcp.yaml -f labs/lab6-ai/k8s/reader-rbac.yaml -f labs/lab6-ai/k8s/otlp-ingress.yaml
python3 scripts/create_ai_access.py "$CONTEXT"
# Restart, in case the key changed.
k -n lab6 rollout restart deployment/signoz-mcp
k -n lab6 rollout status deployment/signoz-mcp --timeout=180s

step "SigNoz's agent skills"
python3 scripts/fetch_signoz_skills.py

step "Smoke test: Lab 6"
python3 scripts/smoke_ai.py "$CONTEXT"

cat <<DONE

Lab 6 is ready.

  MCP server   http://mcp.localhost:8080/mcp
  Ask it       cd labs/lab6-ai/workspace && claude
  On alerts    make investigate    (needs Lab 4)
DONE
