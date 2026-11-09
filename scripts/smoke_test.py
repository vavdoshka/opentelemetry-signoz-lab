#!/usr/bin/env python3
"""Proves a lab's telemetry really reaches SigNoz. Healthy pods do not prove that.

Usage: smoke_test.py 1|2|3
"""

import os
import sys

from signoz_client import LAB3_URL, LAB5_URL, LABS, count, fire, login, metric_exists, query, read_credentials, request, wait_for


def smoke_test_lab5(token):
    """Proves each way Postgres reports on itself reaches SigNoz."""

    def slow_query():
        return request(f"{LAB5_URL}/api/scenario/missing_index", {}, timeout=30)[0] == 200

    wait_for("the app and Postgres", slow_query, timeout=300)
    wait_for(
        "database spans from the app",
        lambda: slow_query() and count(token, "traces", "service.name = 'lab5-app' AND db.system = 'postgresql'", minutes=2),
        timeout=180,
        interval=15,
    )
    # The cluster collector's two receivers. Each fails on its own if its login,
    # address or pipeline is wrong, with no error in the collector's status.
    wait_for("metrics from the postgresql receiver", lambda: metric_exists(token, "postgresql.backends", minutes=3), timeout=180)
    wait_for("metrics from the sqlquery receiver", lambda: metric_exists(token, "postgres.sessions.blocked", minutes=3), timeout=180)
    try:
        wait_for(
            "Postgres's own log, with a query plan",
            lambda: slow_query() and count(token, "logs", "service.name = 'postgres' AND body CONTAINS 'Seq Scan'", minutes=3),
            timeout=180,
            interval=15,
        )
    except SystemExit:
        print(COLLECTORS_STUCK, file=sys.stderr)
        raise
    print("Smoke test passed: Lab 5's spans, statistics and Postgres log are reaching SigNoz.")


COLLECTORS_STUCK = """Spans are arriving but logs aren't, so a SigNoz collector may be stuck while reporting Running.
Count its failures:
  kubectl -n signoz logs -l app.kubernetes.io/component=otel-collector --since=10m --tail=-1 | grep -c 'Dropping data'
If that isn't 0, restart the collectors, then run this again:
  kubectl -n signoz delete pod -l app.kubernetes.io/component=otel-collector"""


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
    # The node log files. Both need settings made when the cluster is created, so
    # a cluster created before them fails here. Rerun `make down` and `make up`.
    wait_for(
        "the API server's audit log",
        lambda: count(token, "logs", "service.name = 'kube-apiserver-audit' AND k8s.audit.user EXISTS", minutes=3),
        timeout=180,
    )
    if os.environ.get("PROVIDER") == "k3d":
        wait_for("k3s's own log", lambda: count(token, "logs", "service.name = 'k3s'", minutes=10), timeout=420)
    if os.environ.get("PROVIDER") == "kind":
        wait_for("the kubelet's log, from journald", lambda: count(token, "logs", "service.name = 'kubelet'", minutes=10), timeout=300)
    print("Smoke test passed: the workload, all four scrape jobs and the node logs are reaching SigNoz.")


def main():
    lab = sys.argv[1] if len(sys.argv) > 1 else ""
    if lab not in (*LABS, "3", "5"):
        raise SystemExit("Usage: smoke_test.py 1|2|3|5")

    credentials = read_credentials()
    if not credentials:
        raise SystemExit("No .lab-credentials, so the smoke test cannot query SigNoz.")
    token = login(credentials)
    if not token:
        raise SystemExit("Could not log in to SigNoz.")

    if lab == "3":
        return smoke_test_lab3(token)
    if lab == "5":
        return smoke_test_lab5(token)
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
    try:
        wait_for(
            "logs linked to traces",
            lambda: count(token, "logs", f"service.name = '{backend}' AND trace_id != ''", minutes=2),
            timeout=60,
        )
    except SystemExit:
        # Spans got through above, so the app and its agent work. After an overload,
        # SigNoz's collectors can stop writing logs and still report Running.
        print(COLLECTORS_STUCK, file=sys.stderr)
        raise
    wait_for(
        "pod names on spans",
        lambda: count(token, "traces", f"service.name = '{backend}' AND k8s.pod.name EXISTS", minutes=2),
        timeout=120,
    )
    wait_for("pod metrics from the node agents", lambda: metric_exists(token, "k8s.pod.cpu.usage"), timeout=180)
    print(f"Smoke test passed: traces, logs and metrics from Lab {lab} are reaching SigNoz.")


if __name__ == "__main__":
    main()
