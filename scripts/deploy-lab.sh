#!/usr/bin/env bash
# Builds a lab's app, deploys it and proves its telemetry reaches SigNoz.
# Rerun it after changing a lab's code. Usage: scripts/deploy-lab.sh 1|2
source "$(dirname "$0")/lib.sh"
cd "$ROOT"

case "${1:-}" in
  1) dir=labs/lab1-hands-off; namespace=lab1; image=telemetry-lab1:dev
     apps="lab1-backend lab1-frontend lab1-loadgen" ;;
  2) dir=labs/lab2-sdk; namespace=lab2; image=telemetry-lab2:dev
     apps="backend frontend loadgen" ;;
  *) echo "Usage: $0 1|2" >&2; exit 1 ;;
esac

step "Lab $1"
docker build -t "$image" "$dir/app"
load_image "$image"

# Lab 1 only. The Instrumentation must exist before the pods start.
if [ -f "$dir/k8s/instrumentation.yaml" ]; then
  k apply -f "$dir/k8s/instrumentation.yaml"
fi
k apply -f "$dir/k8s/app.yaml"

# The image tag does not change, so restart to pick up a new build.
for app in $apps; do
  k -n "$namespace" rollout restart "deployment/$app"
done
for app in postgres $apps; do
  k -n "$namespace" rollout status "deployment/$app" --timeout=300s
done

step "Smoke test: Lab $1"
python3 scripts/smoke_test.py "$1"
