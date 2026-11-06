#!/usr/bin/env bash
# k3d only. The k8s-infra agent mounts the host's / with HostToContainer
# propagation, but a k3d node is a Docker container whose / is a private mount,
# so the pod fails with:
#   path "/" is mounted on "/" but it is not a shared or slave mount
# This marks / as shared inside each node container. It is lost when a node
# restarts, so `make up` always reapplies it. kind nodes do not need this.
source "$(dirname "$0")/lib.sh"

nodes=$(docker ps --format '{{.Names}}' --filter "label=k3d.cluster=$CLUSTER_NAME" | grep -E -- '-(server|agent)-[0-9]+$')
for node in $nodes; do
  docker exec "$node" mount --make-rshared /
done
