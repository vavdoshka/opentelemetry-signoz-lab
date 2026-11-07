#!/usr/bin/env python3
"""Proves a lab's telemetry really reaches SigNoz. Healthy pods do not prove that.

Usage: smoke_test.py 1|2|3
"""

import sys

from signoz_client import LAB3_URL, LABS, count, fire, login, metric_exists, query, read_credentials, request, wait_for


def smoke_test_lab3(token):
    """Lab 3 has no orders. It's there to prove the extra scrape jobs work."""

    def work():
        return request(f"{LAB3_URL}/api/work")[0] == 200

    wait_for("the workload", work, timeout=300)
    wait_for(
        "spans in SigNoz",
        lambda: work() and count(token, "traces", "service.name = 'lab3-workload'", minutes=2),
        timeout=180,
        interval=8,
    )
    # One metric from each scrape job. Each of these fails on its own if the job's
    # permissions, address or keep-list are wrong, with no error in the collector's status.
    for job, metric, expression in (
        ("kubelet", "kubelet_running_pods", ""),
        ("cadvisor", "container_cpu_cfs_periods_total", "namespace = 'lab3'"),
        ("kubelet-probes", "prober_probe_total", "namespace = 'lab3'"),
        ("apiserver", "apiserver_request_total", ""),
    ):
        wait_for(f"{job} metrics", lambda: metric_exists(token, metric, expression, minutes=3), timeout=180)
    # Reported, not required: kube-system pods can stay quiet for minutes, and
    # collection starts at the end of each file.
    spec = {
        "aggregations": [{"expression": "count()"}],
        "filter": {"expression": "k8s.namespace.name = 'kube-system'"},
        "groupBy": [{"name": "k8s.pod.name", "fieldContext": "resource", "fieldDataType": "string"}],
    }
    result = query(token, "logs", spec, "scalar", minutes=10) or {}
    pods = sorted({row[0] for row in result.get("data") or []})
    print(f"kube-system logs in the last 10 minutes, from: {', '.join(pods) or 'none yet'}")
    print("Smoke test passed: the workload and all four scrape jobs are reaching SigNoz.")


def main():
    lab = sys.argv[1] if len(sys.argv) > 1 else ""
    if lab not in (*LABS, "3"):
        raise SystemExit("Usage: smoke_test.py 1|2|3")

    credentials = read_credentials()
    if not credentials:
        raise SystemExit("No .lab-credentials, so the smoke test cannot query SigNoz.")
    token = login(credentials)
    if not token:
        raise SystemExit("Could not log in to SigNoz.")

    if lab == "3":
        return smoke_test_lab3(token)
    backend = LABS[lab]["backend"]

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
