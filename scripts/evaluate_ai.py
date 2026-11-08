#!/usr/bin/env python3
"""Scores Lab 5's AI on incidents whose real causes are already known.

For each case this triggers the real failure, waits for the real alert to
reach Lab 4's sink, runs the AI agent on your machine on that alert, and checks
the report for the facts the earlier labs established by hand. It measures how long each step took and what it cost.

The checks are simple text matches, so they can be fooled: a report that says
"this was NOT an OOM kill" contains "OOM". So every report is saved in full
with its result, in tutorial/data/ai-evaluation.json, to be read by a person.

Each case costs one investigation, about $0.10 to $0.50 on Sonnet, and takes
about 6 minutes, because an alert takes about 4 minutes to fire.

Usage: evaluate_ai.py KUBE_CONTEXT [case ...]
"""

import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from investigate_alerts import investigate
from signoz_client import LAB3_URL, LABS, SIGNOZ_URL, received_alerts, request, session

RESULTS = Path(__file__).resolve().parent.parent / "tutorial/data/ai-evaluation.json"
ALERT_TIMEOUT_S = 480

# "must" facts are the root cause. "should" facts are good evidence.
CASES = {
    "slow_query": {
        "rule": "Lab 1: slow database queries",
        "fire": [(f"{LABS['1']['url']}/api/scenario/slow_query", {})] * 3,
        "truth": "The backend ran SELECT pg_sleep(2), so the query took 2 seconds.",
        "must": {"names the slow SQL": r"pg_sleep"},
        "should": {"names the service": r"lab1-backend", "gives the duration": r"\b2(\.\d+)?\s*(s\b|sec)|\b20\d\d(\.\d+)?\s*ms"},
    },
    "oom": {
        "rule": "Lab 3: container OOM killed",
        "fire": [(f"{LAB3_URL}/api/scenario/oom", {})],
        "truth": "The app leaked memory until the kernel killed it at its 256Mi limit.",
        "must": {"says OOM kill": r"OOM", "ties it to the memory limit": r"256\s*Mi|memory limit"},
        "should": {"names the process": r"uvicorn", "sees memory growing": r"leak|grow|climb|rising|ramp|increas"},
    },
    "throttle": {
        "rule": "Lab 3: CPU throttled",
        "fire": [(f"{LAB3_URL}/api/scenario/throttle", {"seconds": 300, "workers": 2})],
        "truth": "The app burned more CPU than its 200m limit, so the kernel throttled it.",
        "must": {"says throttling": r"throttl", "ties it to the CPU limit": r"200\s*m|CPU limit"},
        "should": {"finds what burned CPU": r"scenario/throttle|burn|worker|subprocess", "gives a throttled share": r"\d+(\.\d+)?\s*%"},
    },
    "liveness": {
        "rule": "Lab 3: killed by a liveness probe",
        "fire": [(f"{LAB3_URL}/api/scenario/liveness", {})],
        "truth": "/healthz started returning 503, so the kubelet killed the container.",
        "must": {"says liveness probe": r"liveness", "finds the failing check": r"503|healthz"},
        "should": {"finds what started it": r"scenario/liveness", "sees the restart": r"restart"},
    },
    "api_denied": {
        "rule": "Lab 3: API calls denied",
        "fire": [(f"{LAB3_URL}/api/scenario/api_denied", {})],
        "truth": "The workload's ServiceAccount listed secrets, which its Role doesn't allow.",
        "must": {"names what was refused": r"secrets", "says it was refused": r"403|forbidden|denied"},
        "should": {"names the caller": r"serviceaccount:lab3:workload|workload", "points at permissions": r"RBAC|Role\b|list-pods|permission"},
    },
}


def utc(seconds=None):
    return datetime.fromtimestamp(seconds or time.time(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def last_termination(context):
    """How Kubernetes says the workload's container last stopped, as a check on the case."""
    run = subprocess.run(["kubectl", "--context", context, "-n", "lab3", "get", "pods", "-o", "json"], capture_output=True, text=True)
    for pod in json.loads(run.stdout)["items"]:
        if pod["metadata"]["name"].startswith("lab3-workload") and not pod["metadata"].get("deletionTimestamp"):
            for container in pod["status"].get("containerStatuses", []):
                ended = (container.get("lastState") or {}).get("terminated")
                if ended:
                    return {"reason": ended.get("reason"), "exitCode": ended.get("exitCode"), "finishedAt": ended.get("finishedAt"), "restarts": container.get("restartCount")}
    return None


def reset_workload(context):
    """A fresh pod, for when a kill from an earlier case keeps an alert firing.

    Only when that's needed: a recent rollout is a false lead for the agent, which
    is what happened when the first version of this script always restarted it.
    """
    for args in (("rollout", "restart"), ("rollout", "status", "--timeout=180s")):
        subprocess.run(["kubectl", "--context", context, "-n", "lab3", *args, "deployment/lab3-workload"], check=True, capture_output=True)


def rule_state(rule):
    status, body = request(f"{SIGNOZ_URL}/api/v2/rules", token=session())
    data = body["data"]
    rules = data.get("rules", []) if isinstance(data, dict) else data
    return next((r.get("state") for r in rules if r["alert"] == rule), None)


def fire(url, body):
    """Triggers a scenario. A pod that has just restarted can answer 502 for a moment."""
    status = 0
    for _ in range(24):
        status, _result = request(url, body, timeout=30)
        if status == 200:
            return status
        time.sleep(5)
    return status


def wait_until_quiet(rule, seconds=900):
    """Waits until the rule has stopped firing, so the next firing is a new alert.

    An OOM alert can take over 12 minutes to resolve, as Lab 4 measured.
    """
    deadline = time.time() + seconds
    while time.time() < deadline:
        state = rule_state(rule)
        if state != "firing":
            return state
        time.sleep(15)
    return "firing"


def collector_drops(context):
    """Batches SigNoz's collectors dropped in the last 10 minutes, as a check on the run.

    An agent can only find what reached SigNoz, so a report is judged differently if
    its evidence was being lost. A collector can do this while reporting itself healthy.
    """
    run = subprocess.run(["kubectl", "--context", context, "-n", "signoz", "get", "pods", "-o", "name"], capture_output=True, text=True)
    drops = 0
    for pod in run.stdout.split():
        if "signoz-otel-collector" in pod:
            logs = subprocess.run(["kubectl", "--context", context, "-n", "signoz", "logs", pod, "--since=10m"], capture_output=True, text=True).stdout
            drops += logs.count("Dropping data")
    return drops


def score(report, facts):
    return {label: bool(re.search(pattern, report, re.IGNORECASE)) for label, pattern in facts.items()}


def run_case(context, name, case):
    print(f"\n=== {name}: {case['rule']}", flush=True)
    # The OOM rule stays true until the pod that was killed is gone.
    if name == "oom" and rule_state(case["rule"]) == "firing":
        print("The rule is still firing from an earlier run, so replacing the pod.", flush=True)
        reset_workload(context)
    state = wait_until_quiet(case["rule"])
    if state == "firing":
        return {"case": name, "rule": case["rule"], "error": "The rule was still firing from an earlier run."}

    fired = time.time()
    for url, body in case["fire"]:
        status = fire(url, body)
        if status != 200:
            return {"case": name, "rule": case["rule"], "error": f"Could not trigger it: HTTP {status} from {url}"}
        time.sleep(3)
    print(f"Triggered at {utc(fired)}. Waiting for the alert...", flush=True)

    alert = None
    deadline = fired + ALERT_TIMEOUT_S
    while time.time() < deadline and not alert:
        alert = next((a for a in received_alerts() if a["status"] == "firing" and a["labels"].get("alertname") == case["rule"] and a["received_ms"] >= fired * 1000), None)
        time.sleep(5)
    if not alert:
        return {"case": name, "rule": case["rule"], "error": f"No alert within {ALERT_TIMEOUT_S} s."}
    alerted = time.time()
    print(f"Alert reached the sink after {round(alerted - fired)} s. Investigating...", flush=True)

    item = investigate(alert)
    report = item.get("report") or ""
    must, should = score(report, case["must"]), score(report, case["should"])
    kubernetes_says = last_termination(context) if name in ("oom", "liveness") else None
    return {
        "case": name,
        "rule": case["rule"],
        "truth": case["truth"],
        "triggered": utc(fired),
        "seconds_to_alert": round(alerted - fired),
        "seconds_to_report": item.get("seconds"),
        "status": item["status"],
        "cost_usd": item.get("cost_usd"),
        "turns": item.get("turns"),
        "denied": item.get("denied"),
        "kubernetes_says": kubernetes_says,
        "collector_drops": collector_drops(context),
        "must": must,
        "should": should,
        "root_cause_found": item["status"] == "done" and all(must.values()),
        "report": report,
    }


def main():
    if len(sys.argv) < 2:
        raise SystemExit("Usage: evaluate_ai.py KUBE_CONTEXT [case ...]")
    context = sys.argv[1]
    names = sys.argv[2:] or list(CASES)
    previous = json.loads(RESULTS.read_text()) if RESULTS.exists() else {"results": []}
    results = {r["case"]: r for r in previous["results"]}
    harness_version = subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout.strip()
    for name in names:
        result = run_case(context, name, CASES[name])
        results[name] = result
        ordered = [results[n] for n in CASES if n in results]
        RESULTS.write_text(json.dumps({"model": "claude-sonnet-5-5", "harness": harness_version, "results": ordered}, indent=1) + "\n")
        print(json.dumps({k: result.get(k) for k in ("root_cause_found", "must", "should", "seconds_to_alert", "seconds_to_report", "cost_usd", "turns", "error")}), flush=True)

    done = [r for r in results.values() if "error" not in r]
    found = sum(r["root_cause_found"] for r in done)
    cost = sum(r.get("cost_usd") or 0 for r in done)
    print(f"\nRoot cause found in {found} of {len(done)} cases, for ${cost:.2f}. Read the reports: the checks are only text matches.")


if __name__ == "__main__":
    main()
