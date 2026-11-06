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
step "Lab 2"
if k get namespace lab2 >/dev/null 2>&1; then
  k -n lab2 get pods -o wide
else
  echo "Not deployed. Run: make lab2"
fi
cat <<DONE

Lab 1     $LAB1_URL
Lab 2     $LAB2_URL
SigNoz    $SIGNOZ_URL  (login in .lab-credentials)
Tutorial  run: make tutorial
DONE
