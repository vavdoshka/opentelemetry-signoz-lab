#!/usr/bin/env python3
"""Creates a lab's SigNoz dashboards, unless they already exist.

Usage: create_dashboard.py 2|3
"""

import json
import subprocess
import sys
from pathlib import Path

from signoz_client import SIGNOZ_URL, request, session

ROOT = Path(__file__).resolve().parent.parent
# SigNoz's own dashboards (Apache-2.0), pinned so upstream changes can't break the lab.
COMMUNITY = "https://raw.githubusercontent.com/SigNoz/dashboards/7d43df2673039ba200e94eb87adcca5674434f0d"
LOCAL = {
    "2": [ROOT / "labs/lab2-custom-dimensions/dashboard.json"],
    "3": [ROOT / "labs/lab3-kubernetes/dashboard.json"],
}
REMOTE = {
    "2": [],
    "3": [
        "k8s-infra-metrics/kubernetes-pod-metrics-detailed.json",
        "k8s-infra-metrics/kubernetes-node-metrics-detailed.json",
        "k8s-system-monitoring/kubernetes-kubelet.json",
        "k8s-system-monitoring/kubernetes-apiserver.json",
    ],
}


def fetch(path):
    # curl, because Python from python.org on macOS has no root certificates by default.
    result = subprocess.run(["curl", "-fsSL", "--max-time", "30", f"{COMMUNITY}/{path}"], capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"Could not download {path}: {result.stderr.strip()}")
    return json.loads(result.stdout)


def main():
    lab = sys.argv[1] if len(sys.argv) > 1 else ""
    if lab not in LOCAL:
        raise SystemExit("Usage: create_dashboard.py 2|3")
    dashboards = [json.loads(path.read_text()) for path in LOCAL[lab] if path.exists()]
    dashboards += [fetch(path) for path in REMOTE[lab]]

    token = session()
    if not token:
        raise SystemExit("Could not log in to SigNoz, so no dashboards were created.")

    # SigNoz answers unknown paths with its web page and a 200, so check for JSON too.
    status, existing = request(f"{SIGNOZ_URL}/api/v2/dashboards", token=token)
    if status != 200 or not existing:
        raise SystemExit(f"Could not list dashboards (HTTP {status}). Check SIGNOZ_URL and the key's role.")
    present = json.dumps(existing["data"])

    # Posting a dashboard twice creates two copies, so check first.
    for dashboard in dashboards:
        name = dashboard["spec"]["display"]["name"]
        if name in present:
            print(f"Dashboard already exists: {name}")
            continue
        status, result = request(f"{SIGNOZ_URL}/api/v2/dashboards", dashboard, token)
        if status not in (200, 201):
            raise SystemExit(f"Could not create {name} (HTTP {status}): {json.dumps(result)[:300]}")
        print(f"Created dashboard: {name}")


if __name__ == "__main__":
    main()
