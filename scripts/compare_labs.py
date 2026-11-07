#!/usr/bin/env python3
"""Sends the same requests to both labs, then shows what SigNoz captured from each."""

import time

from signoz_client import LABS, count, fire, login, metric_exists, read_credentials

SCENARIOS = ["order"] * 5 + ["list", "slow_query", "bad_input", "crash", "backend_500", "db_error", "timeout", "cache_miss"]
WINDOW_MINUTES = 3
# On a fresh boot, a new metric takes a while to become queryable, so a quick
# "no" can be wrong. Keep asking until this many seconds after the spans check.
METRIC_WAIT_SECONDS = 90


def spans(token, expression):
    return count(token, "traces", expression, WINDOW_MINUTES)


def eventually(check, deadline):
    """True if check() succeeds before the deadline. After it, asks just once."""
    while True:
        if check():
            return True
        if time.monotonic() > deadline:
            return False
        time.sleep(10)


def checks(token, lab, deadline):
    """Each check returns a count, or a true/false value."""
    frontend, backend = LABS[lab]["frontend"], LABS[lab]["backend"]
    both = f"service.name IN ('{frontend}', '{backend}')"

    def metric(name, service):
        expression = f"service.name = '{service}'"
        return eventually(lambda: metric_exists(token, name, expression, WINDOW_MINUTES), deadline)

    return [
        ("Spans", spans(token, both)),
        ("Traces crossing both services", spans(token, f"service.name = '{backend}' AND kind_string = 'Server' AND is_remote = 'yes'")),
        ("SQL text on spans", spans(token, f"service.name = '{backend}' AND db.statement EXISTS")),
        ("Spans marked as errors", spans(token, f"{both} AND has_error = true")),
        ("Pod names on spans", spans(token, f"{both} AND k8s.pod.name EXISTS")),
        ("Logs linked to traces", count(token, "logs", f"{both} AND trace_id != ''", WINDOW_MINUTES)),
        ("HTTP metrics", metric("http.server.duration.count", backend)),
        ("Python runtime metrics", metric("cpython.gc.collections", backend)),
        ("Log fields from plain logging (order.item)", count(token, "logs", f"service.name = '{backend}' AND order.item EXISTS", WINDOW_MINUTES)),
        ("Custom span (price_order)", spans(token, f"service.name = '{backend}' AND name = 'price_order'")),
        ("Business attribute on spans (order.item)", spans(token, f"service.name = '{backend}' AND order.item EXISTS")),
        ("Technical attribute on spans (cache.hit)", spans(token, f"service.name = '{backend}' AND cache.hit EXISTS")),
        ("Scenario name on spans (lab.scenario)", spans(token, f"service.name = '{frontend}' AND lab.scenario EXISTS")),
        ("Business metric (orders.created)", metric("orders.created", backend)),
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

    print("Checking what arrived. Metrics can take up to 90 seconds on a fresh boot...", flush=True)
    deadline = time.monotonic() + METRIC_WAIT_SECONDS
    results = {lab: checks(token, lab, deadline) for lab in LABS}
    rows = [(name, show(value), show(results["2"][index][1])) for index, (name, value) in enumerate(results["1"])]
    rows.append(("Trace ID in the API response", show(trace_ids["1"]), show(trace_ids["2"])))

    width = max(len(row[0]) for row in rows)
    print(f"\n{'What SigNoz received':<{width}}  {'Lab 1 (hands-off)':<18}  Lab 2 (custom dimensions)")
    print("-" * (width + 48))
    for name, first, second in rows:
        print(f"{name:<{width}}  {first:<18}  {second}")
    print(f"\nCounts cover the last {WINDOW_MINUTES} minutes, so they include any other traffic.")


if __name__ == "__main__":
    main()
