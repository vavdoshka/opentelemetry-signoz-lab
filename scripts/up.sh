#!/usr/bin/env bash
# Creates the cluster and deploys SigNoz, the node agents and the test app.
# Safe to rerun: it also recovers a lab after Docker or the machine restarts.
source "$(dirname "$0")/lib.sh"
cd "$ROOT"

scripts/check-prereqs.sh

k3d_up() {
  if k3d_cluster_exists; then
    k3d cluster start "$CLUSTER_NAME"
  else
    k3d cluster create --config cluster/k3d-config.yaml
  fi
  scripts/k3d-shared-mount.sh
  k wait --for=condition=Ready node --all --timeout=180s

  # A Docker restart can reassign node IPs, leaving k3s routing a node's kubelet
  # calls to the wrong node. Telemetry still flows, but `kubectl exec` and `logs`
  # fail with an x509 error. Restarting the worker clears it.
  if k get --raw "/api/v1/nodes/k3d-$CLUSTER_NAME-server-0/proxy/healthz" 2>&1 | grep -q x509; then
    echo "Node IPs changed. Restarting the worker to reset its tunnel."
    docker restart "k3d-$CLUSTER_NAME-agent-0" >/dev/null
    sleep 5
    scripts/k3d-shared-mount.sh
    k wait --for=condition=Ready node --all --timeout=180s
  fi
}

kind_up() {
  kind_cluster_exists || kind create cluster --config cluster/kind-config.yaml
  k wait --for=condition=Ready node --all --timeout=180s
  # Let workloads use both nodes, like the k3d cluster.
  k taint nodes --all node-role.kubernetes.io/control-plane- 2>/dev/null || true
  helm repo add traefik https://traefik.github.io/charts --force-update >/dev/null
  helm repo update traefik >/dev/null
  h upgrade --install traefik traefik/traefik --version "$TRAEFIK_CHART_VERSION" \
    --namespace traefik --create-namespace -f cluster/traefik-kind-values.yaml --wait
}

step "Cluster ($PROVIDER)"
"${PROVIDER}_up"

step "SigNoz"
helm repo add signoz https://charts.signoz.io --force-update >/dev/null
helm repo update signoz >/dev/null
h upgrade --install signoz signoz/signoz --version "$SIGNOZ_CHART_VERSION" \
  --namespace signoz --create-namespace -f signoz/signoz-values.yaml
k apply -f k8s/signoz-ingress.yaml
python3 scripts/bootstrap_signoz.py

step "Node agents"
h upgrade --install k8s-infra signoz/k8s-infra --version "$K8S_INFRA_CHART_VERSION" \
  --namespace signoz -f signoz/k8s-infra-values.yaml

step "Test app"
scripts/deploy-app.sh

step "Smoke test"
python3 scripts/smoke_test.py

cat <<DONE

Lab is ready.

  Test app  $APP_URL
  SigNoz    $SIGNOZ_URL  (login in .lab-credentials)
  Tutorial  run: make tutorial
DONE
