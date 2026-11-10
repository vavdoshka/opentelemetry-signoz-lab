#!/usr/bin/env bash
# Builds a lab's app, deploys it and proves its telemetry reaches SigNoz.
# Rerun it after changing a lab's code. Usage: scripts/deploy-lab.sh 1|2|3|5
source "$(dirname "$0")/lib.sh"
cd "$ROOT"

case "${1:-}" in
  1) dir=labs/lab1-hands-off; namespace=lab1; image=telemetry-lab1:dev
     apps="lab1-backend lab1-frontend lab1-loadgen" ;;
  2) dir=labs/lab2-custom-dimensions; namespace=lab2; image=telemetry-lab2:dev
     apps="backend frontend loadgen" ;;
  3) dir=labs/lab3-kubernetes; namespace=lab3; image=telemetry-lab3:dev
     apps="lab3-workload lab3-loadgen" ;;
  5) dir=labs/lab5-postgres; namespace=lab5; image=telemetry-lab5:dev
     apps="lab5-app" ;;
  *) echo "Usage: $0 1|2|3|5" >&2; exit 1 ;;
esac

step "Lab $1"
docker build -t "$image" "$dir/app"
load_image "$image"

# The Instrumentation must exist before the pods start.
k apply -f "$dir/k8s/instrumentation.yaml"
k apply -f "$dir/k8s/app.yaml"

if [ "$1" = 3 ]; then
  k apply -f "$dir/k8s/kernel-log.yaml" -f "$dir/k8s/audit-log.yaml"
  readers="kernel-log audit-log"
  # kind's kubelet logs to journald. k3d nodes have no journald, and k3s's log
  # file covers the kubelet there. Restart this reader first, so it's following
  # the journal while the others restart, and the smoke test has lines to find.
  if [ "$PROVIDER" = kind ]; then
    k apply -f "$dir/k8s/journal-log.yaml"
    readers="journal-log $readers"
  fi
  step "Extra scrape jobs and logs"
  k apply -f "$dir/k8s/metrics-rbac.yaml"
  install_k8s_infra
  k -n signoz rollout status deployment/k8s-infra-otel-deployment --timeout=180s
  k -n signoz rollout status daemonset/k8s-infra-otel-agent --timeout=180s
fi

if [ "$1" = 5 ]; then
  # Wait for Postgres to load its table first. Restarting the collectors at the same
  # time overloaded a 4-CPU machine, and left SigNoz's collectors stuck.
  k -n "$namespace" rollout status deployment/postgres --timeout=300s
  step "Postgres logs and statistics"
  k apply -f "$dir/k8s/monitor-secret.yaml"
  # Helm restarts the collectors only if their config changed. Restarting them anyway
  # would register every metric series again, which is needless work for ClickHouse.
  install_k8s_infra
  k -n signoz rollout status deployment/k8s-infra-otel-deployment --timeout=180s
  k -n signoz rollout status daemonset/k8s-infra-otel-agent --timeout=180s
fi

# The image tag does not change, so restart to pick up a new build.
for app in $apps; do
  k -n "$namespace" rollout restart "deployment/$app"
done
for app in $apps; do
  k -n "$namespace" rollout status "deployment/$app" --timeout=300s
done
if [ "$1" != 3 ]; then
  k -n "$namespace" rollout status deployment/postgres --timeout=300s
else
  for daemonset in $readers; do
    k -n "$namespace" rollout restart "daemonset/$daemonset"
    k -n "$namespace" rollout status "daemonset/$daemonset" --timeout=180s
  done
fi

# The Operator's webhook fails open: if it can't answer, pods start without the
# agent and nothing reports an error. So check, rather than trust a healthy pod.
missing=$(k -n "$namespace" get pods -o json | python3 -c '
import json, sys
for pod in json.load(sys.stdin)["items"]:
    meta = pod["metadata"]
    names = [c["name"] for c in pod["spec"].get("initContainers", [])]
    opted_out = meta.get("annotations", {}).get("instrumentation.opentelemetry.io/inject-python") == "false"
    if not meta.get("deletionTimestamp") and not opted_out and not any("opentelemetry" in n for n in names):
        print(meta["name"])')
if [ -n "$missing" ]; then
  echo "These pods started without the OpenTelemetry agent:" >&2
  echo "$missing" >&2
  echo "The Operator's webhook may not have been ready. Rerun: make lab$1" >&2
  exit 1
fi

if [ "$1" = 3 ]; then
  step "Log pipeline"
  # Lab 3's app prints its logs, with trace IDs, instead of sending them over
  # OTLP. This SigNoz pipeline reads the IDs back out. See k8s/instrumentation.yaml.
  python3 scripts/create_log_pipeline.py "$dir/log-pipeline.json"
fi

step "Smoke test: Lab $1"
# PROVIDER tells the Lab 3 test whether to expect k3s's log.
PROVIDER="$PROVIDER" python3 scripts/smoke_test.py "$1"

if [ "$1" != 1 ]; then
  step "Dashboard"
  python3 scripts/create_dashboard.py "$1"
fi
