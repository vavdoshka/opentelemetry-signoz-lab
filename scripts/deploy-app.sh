#!/usr/bin/env bash
# Builds the test app image, loads it into the cluster and rolls it out.
source "$(dirname "$0")/lib.sh"
cd "$ROOT"

docker build -t "$IMAGE" app
case "$PROVIDER" in
  k3d)  k3d image import "$IMAGE" --cluster "$CLUSTER_NAME" ;;
  kind) kind load docker-image "$IMAGE" --name "$CLUSTER_NAME" ;;
esac

k apply -f k8s/app.yaml
# The image tag does not change, so restart to pick up a new build.
k -n lab rollout restart deployment/backend deployment/frontend deployment/loadgen
for deployment in postgres backend frontend loadgen; do
  k -n lab rollout status "deployment/$deployment" --timeout=300s
done
