#!/usr/bin/env bash
# Shared settings and helpers, sourced by the other scripts.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLUSTER_NAME="signoz-lab"
SIGNOZ_CHART_VERSION="0.149.0"
K8S_INFRA_CHART_VERSION="0.17.1"
OTEL_OPERATOR_CHART_VERSION="0.129.0"
TRAEFIK_CHART_VERSION="41.7.1"
SIGNOZ_URL="http://signoz.localhost:8080"
LAB1_URL="http://lab1.localhost:8080"
LAB2_URL="http://lab2.localhost:8080"
LAB3_URL="http://lab3.localhost:8080"
LAB4_URL="http://lab4.localhost:8080"

kind_cluster_exists() {
  command -v kind >/dev/null 2>&1 && kind get clusters 2>/dev/null | grep -qx "$CLUSTER_NAME"
}

k3d_cluster_exists() {
  command -v k3d >/dev/null 2>&1 && k3d cluster get "$CLUSTER_NAME" >/dev/null 2>&1
}

# Use PROVIDER if set, otherwise whichever cluster already exists.
if [ -z "${PROVIDER:-}" ]; then
  if kind_cluster_exists; then PROVIDER=kind; else PROVIDER=k3d; fi
fi

case "$PROVIDER" in
  k3d)  CONTEXT="k3d-$CLUSTER_NAME" ;;
  kind) CONTEXT="kind-$CLUSTER_NAME" ;;
  *)    echo "PROVIDER must be k3d or kind, not '$PROVIDER'" >&2; exit 1 ;;
esac

# Always name the context, so these scripts can never touch another cluster.
k() { kubectl --context "$CONTEXT" "$@"; }
h() { helm --kube-context "$CONTEXT" "$@"; }

load_image() {
  case "$PROVIDER" in
    k3d)  k3d image import "$1" --cluster "$CLUSTER_NAME" ;;
    kind) kind load docker-image "$1" --name "$CLUSTER_NAME" ;;
  esac
}

# Lab 3 adds scrape jobs. Keep them when `make up` reruns, or an upgrade would
# remove them with no error.
install_k8s_infra() {
  local values=(-f signoz/k8s-infra-values.yaml)
  if k get namespace lab3 >/dev/null 2>&1; then
    values+=(-f labs/lab3-kubernetes/k8s-infra-values.yaml)
  fi
  h upgrade --install k8s-infra signoz/k8s-infra --version "$K8S_INFRA_CHART_VERSION" \
    --namespace signoz "${values[@]}"
}

step() { printf '\n==> %s\n' "$*"; }
