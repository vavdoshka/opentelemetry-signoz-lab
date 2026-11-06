#!/usr/bin/env python3
"""Proves a lab's telemetry really reaches SigNoz. Healthy pods do not prove that.

Usage: smoke_test.py 1|2
"""

import sys

from signoz_client import LABS, count, fire, login, metric_exists, read_credentials, wait_for


def main():
    lab = sys.argv[1] if len(sys.argv) > 1 else ""
    if lab not in LABS:
        raise SystemExit("Usage: smoke_test.py 1|2")
    backend = LABS[lab]["backend"]

    credentials = read_credentials()
    if not credentials:
        raise SystemExit("No .lab-credentials, so the smoke test cannot query SigNoz.")
    token = login(credentials)
    if not token:
        raise SystemExit("Could not log in to SigNoz.")

    def order_succeeds():
        return fire(lab, "order")[0] == 200

    def spans_arrive():
        fire(lab, "order")
        return count(token, "traces", f"service.name = '{backend}'", minutes=2)

    def cross_service_span():
        fire(lab, "order")
        return count(token, "traces", f"service.name = '{backend}' AND kind_string = 'Server' AND is_remote = 'yes'", minutes=2)

    wait_for("the app", order_succeeds, timeout=300)
    wait_for("spans in SigNoz", spans_arrive, timeout=300, interval=8)
    wait_for("a trace crossing both services", cross_service_span, timeout=120)
    wait_for(
        "logs linked to traces",
        lambda: count(token, "logs", f"service.name = '{backend}' AND trace_id != ''", minutes=2),
        timeout=60,
    )
    wait_for(
        "pod names on spans",
        lambda: count(token, "traces", f"service.name = '{backend}' AND k8s.pod.name EXISTS", minutes=2),
        timeout=120,
    )
    wait_for("pod metrics from the node agents", lambda: metric_exists(token, "k8s.pod.cpu.usage"), timeout=180)
    print(f"Smoke test passed: traces, logs and metrics from Lab {lab} are reaching SigNoz.")


if __name__ == "__main__":
    main()
