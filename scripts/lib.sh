#!/usr/bin/env bash
# Shared settings and helpers, sourced by the other scripts.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLUSTER_NAME="signoz-lab"
IMAGE="telemetry-lab:dev"
SIGNOZ_CHART_VERSION="0.149.0"
K8S_INFRA_CHART_VERSION="0.17.1"
TRAEFIK_CHART_VERSION="42.3.1"
SIGNOZ_URL="http://signoz.localhost:8080"
APP_URL="http://app.localhost:8080"

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

step() { printf '\n==> %s\n' "$*"; }
