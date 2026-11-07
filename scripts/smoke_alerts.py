#!/usr/bin/env python3
"""Proves the whole alert path: a real failure has to end up at Lab 4's sink.

A test notification only proves the channel. This needs Kubernetes, the node
agents, SigNoz's rule and Alertmanager to all work. It restarts Lab 3's workload.
"""

from signoz_client import LAB3_URL, received_alerts, request, wait_for

RULE = "Lab 3: killed by a liveness probe"


def main():
    status, _ = request(f"{LAB3_URL}/api/scenario/liveness", {})
    if status != 200:
        raise SystemExit(f"Could not fire the liveness scenario (HTTP {status}).")
    wait_for(
        f"'{RULE}' at the sink",
        lambda: any(alert["labels"].get("alertname") == RULE and alert["status"] == "firing" for alert in received_alerts()),
        timeout=300,
    )
    print("Smoke test passed: a real failure reached the alert sink.")


if __name__ == "__main__":
    main()
