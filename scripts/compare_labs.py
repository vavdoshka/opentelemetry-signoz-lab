#!/usr/bin/env python3
"""Sends the same requests to both labs, then shows what SigNoz captured from each."""

import time

from signoz_client import LABS, count, fire, login, metric_exists, read_credentials

SCENARIOS = ["order"] * 5 + ["list", "slow_query", "bad_input", "crash", "backend_500", "db_error", "timeout"]
WINDOW_MINUTES = 3


def spans(token, expression):
    return count(token, "traces", expression, WINDOW_MINUTES)


def checks(token, lab):
    """Each check returns a count, or a true/false value."""
    frontend, backend = LABS[lab]["frontend"], LABS[lab]["backend"]
    both = f"service.name IN ('{frontend}', '{backend}')"
    return [
        ("Spans", spans(token, both)),
        ("Traces crossing both services", spans(token, f"service.name = '{backend}' AND kind_string = 'Server' AND is_remote = 'yes'")),
        ("SQL text on spans", spans(token, f"service.name = '{backend}' AND db.statement EXISTS")),
        ("Spans marked as errors", spans(token, f"{both} AND has_error = true")),
        ("Pod names on spans", spans(token, f"{both} AND k8s.pod.name EXISTS")),
        ("Logs linked to traces", count(token, "logs", f"{both} AND trace_id != ''", WINDOW_MINUTES)),
        ("HTTP metrics", metric_exists(token, "http.server.duration.count", f"service.name = '{backend}'", WINDOW_MINUTES)),
        ("Python runtime metrics", metric_exists(token, "cpython.gc.collections", f"service.name = '{backend}'", WINDOW_MINUTES)),
        ("Custom span (price_order)", spans(token, f"service.name = '{backend}' AND name = 'price_order'")),
        ("Business attribute on spans (order.item)", spans(token, f"service.name = '{backend}' AND order.item EXISTS")),
        ("Scenario name on spans (lab.scenario)", spans(token, f"service.name = '{frontend}' AND lab.scenario EXISTS")),
        ("Business metric (orders.created)", metric_exists(token, "orders.created", f"service.name = '{backend}'", WINDOW_MINUTES)),
    ]


def show(value):
    if value is True:
        return "yes"
    if value is False or value == 0:
        return "no"
    return f"yes ({value})"


def main():
    credentials = read_credentials()
    token = login(credentials) if credentials else None
    if not token:
        raise SystemExit("Could not log in to SigNoz. Check .lab-credentials.")

    trace_ids = {}
    for lab in LABS:
        status, body = fire(lab, "order")
        if status != 200:
            raise SystemExit(f"Lab {lab} is not answering. Run: make {'up' if lab == '1' else 'lab2'}")
        trace_ids[lab] = bool(body.get("trace_id"))

    print(f"Sending the same {len(SCENARIOS)} requests to both labs...", flush=True)
    for scenario in SCENARIOS:
        for lab in LABS:
            fire(lab, scenario)
    print("Waiting for telemetry to arrive...", flush=True)
    time.sleep(25)

    results = {lab: checks(token, lab) for lab in LABS}
    rows = [(name, show(value), show(results["2"][index][1])) for index, (name, value) in enumerate(results["1"])]
    rows.append(("Trace ID in the API response", show(trace_ids["1"]), show(trace_ids["2"])))

    width = max(len(row[0]) for row in rows)
    print(f"\n{'What SigNoz received':<{width}}  {'Lab 1 (hands-off)':<18}  Lab 2 (SDK)")
    print("-" * (width + 34))
    for name, first, second in rows:
        print(f"{name:<{width}}  {first:<18}  {second}")
    print(f"\nCounts cover the last {WINDOW_MINUTES} minutes, so they include any other traffic.")


if __name__ == "__main__":
    main()
