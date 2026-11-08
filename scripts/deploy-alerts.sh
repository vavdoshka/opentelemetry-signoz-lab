#!/usr/bin/env bash
# Deploys Lab 4's alert sink, then creates its channel and rules in SigNoz.
# Safe to rerun. Change a rule in labs/lab4-alerts/alerts.json and run this again.
source "$(dirname "$0")/lib.sh"
cd "$ROOT"

# Some rules read metrics only Lab 3 collects. Without it they would never fire,
# and nothing would tell you.
if ! k get namespace lab3 >/dev/null 2>&1; then
  echo "Lab 4 alerts on Lab 3's metrics, so deploy that first: make lab3" >&2
  exit 1
fi

step "Lab 4"
docker build -t telemetry-lab4:dev labs/lab4-alerts/app
load_image telemetry-lab4:dev
k apply -f labs/lab4-alerts/k8s/sink.yaml
k -n lab4 rollout restart deployment/alert-sink
k -n lab4 rollout status deployment/alert-sink --timeout=120s

step "Alert rules"
python3 scripts/create_alerts.py
# Rewriting the rules drops Lab 5's channel from them. Put it back, or alerts
# would silently stop reaching the investigator.
if k get namespace lab5 >/dev/null 2>&1; then
  python3 scripts/create_ai_routes.py
fi

cat <<DONE

Lab 4 is ready.

  Alert sink  $LAB4_URL
  Rules       $SIGNOZ_URL/alerts
DONE
