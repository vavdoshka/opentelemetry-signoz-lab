#!/usr/bin/env python3
"""Investigates Lab 4's alerts with the AI agent on your machine.

Watches what SigNoz sends to Lab 4's sink. For each alert listed in
labs/lab6-ai/investigate.json that starts firing, it runs your agent once in
labs/lab6-ai/workspace, with that directory's instructions, MCP connection and
permissions, and saves the report in labs/lab6-ai/reports/. The agent uses the
login it already has.

It polls the sink, so nothing has to reach into your machine, and it only looks
for new alerts while it's running.

Each investigation costs about $0.20 on Sonnet 5.5, on your plan or API key.

Usage: investigate_alerts.py [claude|opencode|codex]    Ctrl-C to stop.
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from signoz_client import received_alerts

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = ROOT / "labs/lab6-ai/workspace"
REPORTS = ROOT / "labs/lab6-ai/reports"
RULES = ROOT / "labs/lab6-ai/investigate.json"

MAX_TURNS = "40"
# A cap on Claude Code's own cost estimate for one investigation.
MAX_BUDGET_USD = "1.00"
# So a flapping alert can't run up a bill.
MAX_PER_HOUR = 10
TIMEOUT_S = 900

PROMPT = """A SigNoz alert just fired. Find out why, using the signoz-investigating-alerts skill if you have it.

Alert: {alertname}
Severity: {severity}
Started firing: {startsAt}
Summary: {summary}
Description: {description}
Labels: {labels}

Answer as AGENTS.md describes."""


def command(harness, prompt):
    if harness == "claude":
        return [
            "claude", "-p", prompt,
            # Leave out your user settings, whose hooks could rewrite commands.
            "--setting-sources", "project,local",
            # Claude Code ignores a folder's allow list until someone trusts the
            # folder interactively, so pass the same file explicitly.
            "--settings", ".claude/settings.json",
            # Only this MCP server, not any others you've set up.
            "--strict-mcp-config", "--mcp-config", ".mcp.json",
            # Anything those settings don't allow is refused, not asked.
            "--permission-mode", "dontAsk",
            "--max-turns", MAX_TURNS,
            "--max-budget-usd", MAX_BUDGET_USD,
            "--output-format", "json",
        ]
    if harness == "opencode":
        return ["opencode", "run", prompt]
    if harness == "codex":
        return ["codex", "exec", prompt]
    raise SystemExit("HARNESS must be claude, opencode or codex.")


def save(item):
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / item["file"]).write_text(json.dumps(item, indent=1) + "\n")


def investigate(alert, harness="claude"):
    """Runs the agent on one alert, and returns its saved report."""
    labels = alert.get("labels", {})
    annotations = alert.get("annotations", {})
    name = labels.get("alertname", "")
    prompt = PROMPT.format(
        alertname=name,
        severity=labels.get("severity", ""),
        startsAt=alert.get("startsAt", ""),
        summary=annotations.get("summary", ""),
        description=annotations.get("description", ""),
        labels=json.dumps(labels, sort_keys=True),
    )
    started = time.time()
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime(started))
    item = {
        "file": f"{stamp}-{re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')}.json",
        "key": f"{name}|{alert.get('startsAt')}",
        "alertname": name,
        "severity": labels.get("severity", ""),
        "startsAt": alert.get("startsAt", ""),
        "started_s": started,
        "harness": harness,
        "status": "running",
    }
    save(item)
    # kubectl in the agent's commands uses the read-only account, not your login.
    env = {**os.environ, "KUBECONFIG": str(WORKSPACE / ".kubeconfig")}
    try:
        run = subprocess.run(command(harness, prompt), cwd=WORKSPACE, env=env, capture_output=True, text=True, timeout=TIMEOUT_S)
        if harness == "claude":
            result = json.loads(run.stdout) if run.stdout.strip() else {}
            item.update(
                status="done" if run.returncode == 0 and not result.get("is_error") else "failed",
                report=result.get("result") or run.stderr[-2000:],
                cost_usd=result.get("total_cost_usd"),
                turns=result.get("num_turns"),
                denied=[d.get("tool_name") for d in result.get("permission_denials") or []],
            )
        else:
            # These print the report as plain text, with no cost or turn count.
            item.update(status="done" if run.returncode == 0 else "failed", report=run.stdout or run.stderr[-2000:])
    except subprocess.TimeoutExpired:
        item.update(status="failed", report=f"Stopped after {TIMEOUT_S} seconds.")
    except FileNotFoundError:
        item.update(status="failed", report=f"{harness} isn't installed.")
    except ValueError:
        item.update(status="failed", report="Claude Code didn't return JSON.")
    item["seconds"] = round(time.time() - started)
    save(item)
    return item


def main():
    harness = sys.argv[1] if len(sys.argv) > 1 else "claude"
    rules = {entry["rule"] for entry in json.loads(RULES.read_text())["investigate"]}
    print(f"Watching for {len(rules)} alerts, with {harness}. Reports go to {REPORTS.relative_to(ROOT)}. Ctrl-C to stop.", flush=True)
    since = int(time.time() * 1000)
    seen, started = set(), []
    while True:
        # Oldest first, one at a time, which keeps the cost predictable.
        for alert in reversed(received_alerts()):
            key = f"{alert['labels'].get('alertname')}|{alert.get('startsAt')}"
            if alert["status"] != "firing" or alert["received_ms"] < since or key in seen or alert["labels"].get("alertname") not in rules:
                continue
            seen.add(key)
            started = [s for s in started if s > time.time() - 3600]
            name = alert["labels"]["alertname"]
            if len(started) >= MAX_PER_HOUR:
                print(f"Skipped {name}: {MAX_PER_HOUR} investigations already started in the last hour.", flush=True)
                continue
            started.append(time.time())
            print(f"\n=== {name}, fired {alert.get('startsAt', '')[:19]}. Investigating...", flush=True)
            item = investigate(alert, harness)
            cost = f", ${item['cost_usd']:.2f}" if item.get("cost_usd") is not None else ""
            print(f"{item['report']}\n\n[{item['status']} in {item['seconds']} s{cost}. Saved as {item['file']}]", flush=True)
        time.sleep(5)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
