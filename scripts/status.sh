#!/usr/bin/env bash
# Shows nodes, pods and URLs.
source "$(dirname "$0")/lib.sh"

echo "Provider: $PROVIDER"
step "Nodes"
k get nodes
step "Test app"
k -n lab get pods -o wide
step "SigNoz"
k -n signoz get pods -o wide
cat <<DONE

Test app  $APP_URL
SigNoz    $SIGNOZ_URL  (login in .lab-credentials)
Tutorial  run: make tutorial
DONE
