#!/usr/bin/env bash
# Deletes the cluster and everything stored in it.
source "$(dirname "$0")/lib.sh"

case "$PROVIDER" in
  k3d)  k3d cluster delete "$CLUSTER_NAME" ;;
  kind) kind delete cluster --name "$CLUSTER_NAME" ;;
esac
