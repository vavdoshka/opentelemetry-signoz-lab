#!/usr/bin/env bash
# Creates the cluster and deploys SigNoz, the node agents, the OpenTelemetry
# Operator and Lab 1.
# Safe to rerun: it also recovers a lab after Docker or the machine restarts.
source "$(dirname "$0")/lib.sh"
cd "$ROOT"

scripts/check-prereqs.sh

# After Docker or a node restarts, the API server takes a while to come back,
# and `kubectl wait` fails at once if it can't connect.
wait_for_api_server() {
  for _ in $(seq 90); do
    k get --raw /readyz >/dev/null 2>&1 && return
    sleep 2
  done
  echo "The API server did not come up within 3 minutes." >&2
  if [ "$PROVIDER" = k3d ]; then
    echo "If you restarted one node by itself, its IP may have changed, and k3d's load" >&2
    echo "balancer still uses the old one. Run: docker restart k3d-$CLUSTER_NAME-serverlb" >&2
  fi
  exit 1
}

k3d_up() {
  if k3d_cluster_exists; then
    k3d cluster start "$CLUSTER_NAME"
  else
    k3d cluster create --config cluster/k3d-config.yaml
  fi
  scripts/k3d-shared-mount.sh
  wait_for_api_server
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
k apply -f signoz/ingress.yaml
python3 scripts/bootstrap_signoz.py

step "Node agents"
install_k8s_infra

step "OpenTelemetry Operator"
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts --force-update >/dev/null
helm repo update open-telemetry >/dev/null
h upgrade --install opentelemetry-operator open-telemetry/opentelemetry-operator \
  --version "$OTEL_OPERATOR_CHART_VERSION" --namespace opentelemetry-operator-system \
  --create-namespace -f cluster/otel-operator-values.yaml --wait --timeout 5m

scripts/deploy-lab.sh 1

cat <<DONE

Lab 1 is ready.

  Lab 1     $LAB1_URL
  SigNoz    $SIGNOZ_URL  (login in .lab-credentials)
  Tutorial  run: make tutorial
  Lab 2     run: make lab2
  Lab 3     run: make lab3
  Lab 4     run: make lab4
DONE
