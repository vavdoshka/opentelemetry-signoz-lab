#!/usr/bin/env python3
"""Proves telemetry really reaches SigNoz. Healthy pods do not prove that."""

import time

from signoz_client import APP_URL, SIGNOZ_URL, login, read_credentials, request, wait_for


def query(token, signal, spec, request_type, minutes=10):
    end = int(time.time() * 1000)
    body = {
        "schemaVersion": "v1",
        "start": end - minutes * 60_000,
        "end": end,
        "requestType": request_type,
        "compositeQuery": {"queries": [{"type": "builder_query", "spec": {"name": "A", "signal": signal, **spec}}]},
        "formatOptions": {"formatTableResultForUI": False, "fillGaps": False},
        "variables": {},
    }
    status, result = request(f"{SIGNOZ_URL}/api/v5/query_range", body, token, timeout=30)
    if status != 200 or not result:
        return None
    return result["data"]["data"]["results"][0]


def count(token, signal, expression):
    spec = {"aggregations": [{"expression": "count()"}], "filter": {"expression": expression}}
    result = query(token, signal, spec, "scalar")
    try:
        return result["data"][0][-1]
    except (KeyError, IndexError, TypeError):
        return 0


def place_order():
    status, body = request(f"{APP_URL}/api/scenario/order", {})
    return body.get("trace_id") if status == 200 and body else None


def main():
    credentials = read_credentials()
    if not credentials:
        raise SystemExit("No .lab-credentials, so the smoke test cannot query SigNoz.")
    token = login(credentials)
    if not token:
        raise SystemExit("Could not log in to SigNoz.")

    wait_for("the test app", place_order, timeout=300)

    def trace_arrives():
        trace_id = place_order()
        time.sleep(8)
        return trace_id if count(token, "traces", f"trace_id = '{trace_id}'") >= 5 else None

    trace_id = wait_for("a trace across both services", trace_arrives, timeout=300, interval=2)
    wait_for("logs linked to that trace", lambda: count(token, "logs", f"trace_id = '{trace_id}'"), timeout=60)
    wait_for("pod names on spans", lambda: count(token, "traces", "k8s.pod.name EXISTS"), timeout=120)

    def infrastructure_metrics():
        spec = {
            "aggregations": [{"metricName": "k8s.pod.cpu.usage", "timeAggregation": "avg", "spaceAggregation": "max"}],
            "stepInterval": 60,
        }
        result = query(token, "metrics", spec, "time_series")
        return result and any(aggregation.get("series") for aggregation in result.get("aggregations") or [])

    wait_for("pod metrics from the node agents", infrastructure_metrics, timeout=180)
    print("Smoke test passed: traces, logs and metrics are reaching SigNoz.")


if __name__ == "__main__":
    main()
