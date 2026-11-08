#!/usr/bin/env bash
# Deploys Lab 5: SigNoz's MCP server, read-only access for AI agents, and the
# alert investigator. Safe to rerun.
source "$(dirname "$0")/lib.sh"
cd "$ROOT"

# The investigator works on Lab 4's alerts.
if ! k get namespace lab4 >/dev/null 2>&1; then
  echo "Lab 5 investigates Lab 4's alerts, so deploy that first: make lab4" >&2
  exit 1
fi

step "MCP server and read-only access"
k apply -f labs/lab5-ai/k8s/mcp.yaml -f labs/lab5-ai/k8s/reader-rbac.yaml
python3 scripts/create_ai_access.py "$CONTEXT"
# Restart, in case the key changed.
k -n lab5 rollout restart deployment/signoz-mcp
k -n lab5 rollout status deployment/signoz-mcp --timeout=180s

step "SigNoz's agent skills"
python3 scripts/fetch_signoz_skills.py

step "Investigator"
# The Claude login stays out of git and out of the image: it goes from
# .lab-ai-credentials into a Secret. --from-env-file keeps it out of the
# process list.
if [ -f .lab-ai-credentials ]; then
  k -n lab5 create secret generic claude-auth --from-env-file=.lab-ai-credentials \
    --dry-run=client -o yaml | k apply -f -
else
  echo "No .lab-ai-credentials, so alerts will reach the investigator but it can't run Claude Code."
  echo "To fix it, see the Lab 5 page of the tutorial, then rerun: make lab5"
fi
docker build -t telemetry-lab5:dev labs/lab5-ai
load_image telemetry-lab5:dev
k apply -f labs/lab5-ai/k8s/investigator.yaml
k -n lab5 rollout restart deployment/investigator
k -n lab5 rollout status deployment/investigator --timeout=180s

step "Alerts to investigate"
python3 scripts/create_ai_routes.py

step "Smoke test: Lab 5"
python3 scripts/smoke_ai.py "$CONTEXT"

cat <<DONE

Lab 5 is ready.

  MCP server     http://mcp.localhost:8080/mcp
  Investigations $LAB5_URL
  Interactive    cd labs/lab5-ai/workspace && claude
DONE
