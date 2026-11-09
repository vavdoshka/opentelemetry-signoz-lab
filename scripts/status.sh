#!/usr/bin/env bash
# Shows nodes, pods and URLs.
source "$(dirname "$0")/lib.sh"

echo "Provider: $PROVIDER"
step "Nodes"
k get nodes
step "SigNoz"
k -n signoz get pods -o wide
step "Lab 1"
k -n lab1 get pods -o wide
for lab in 2 3 4 5; do
  step "Lab $lab"
  if k get namespace "lab$lab" >/dev/null 2>&1; then
    k -n "lab$lab" get pods -o wide
  else
    echo "Not deployed. Run: make lab$lab"
  fi
done
cat <<DONE

Lab 1     $LAB1_URL
Lab 2     $LAB2_URL
Lab 3     $LAB3_URL
Lab 4     $LAB4_URL
Lab 5     $LAB5_URL  (optional)
MCP       http://mcp.localhost:8080/mcp
SigNoz    $SIGNOZ_URL  (to see the login: cat .lab-credentials)
Tutorial  run: make tutorial
DONE
