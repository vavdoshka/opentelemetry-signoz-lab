"""Investigates SigNoz alerts with an AI agent, and shows its reports.

SigNoz's webhook channel posts Alertmanager's payload to POST /webhook, as it
does to Lab 4's sink. For each alert that starts firing, this runs one headless
Claude Code investigation in /workspace, the same workspace you use on your
machine, and keeps the report. See them at /, or as JSON at
/api/investigations. Standard library only.

The agent can only read: SigNoz through the MCP server's viewer key, and
Kubernetes through this pod's read-only ServiceAccount.
"""

import html
import json
import os
import queue
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WORKSPACE = os.environ.get("WORKSPACE", "/workspace")
MCP_CONFIG = os.environ.get("MCP_CONFIG", "/etc/investigator/mcp.json")
MODEL = os.environ.get("MODEL", "sonnet")
MAX_TURNS = os.environ.get("MAX_TURNS", "40")
# A cap on Claude Code's own cost estimate for one investigation.
MAX_BUDGET_USD = os.environ.get("MAX_BUDGET_USD", "1.00")
# A cap on investigations an hour, so a flapping alert can't run up a bill.
MAX_PER_HOUR = int(os.environ.get("MAX_PER_HOUR", "10"))
TIMEOUT_S = int(os.environ.get("TIMEOUT_S", "900"))
DATA_FILE = Path(os.environ.get("DATA_FILE", "/data/investigations.json"))

PROMPT = """A SigNoz alert just fired. Find out why, using the signoz-investigating-alerts skill.

Alert: {alertname}
Severity: {severity}
Started firing: {startsAt}
Summary: {summary}
Description: {description}
Labels: {labels}

Answer as AGENTS.md describes."""

lock = threading.Lock()
investigations = json.loads(DATA_FILE.read_text()) if DATA_FILE.exists() else []
work = queue.Queue()


def save():
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(investigations, indent=1))


def started_in_last_hour():
    cutoff = time.time() - 3600
    return sum(1 for item in investigations if item.get("started_s", 0) > cutoff)


def accept(alert):
    """Queues an investigation for a newly firing alert. Repeats are ignored."""
    labels = alert.get("labels", {})
    key = f"{labels.get('alertname')}|{alert.get('startsAt')}"
    with lock:
        if alert.get("status") != "firing" or any(item["key"] == key for item in investigations):
            return
        item = {
            "key": key,
            "alertname": labels.get("alertname", ""),
            "severity": labels.get("severity", ""),
            "startsAt": alert.get("startsAt", ""),
            "received": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": "queued",
            "prompt": PROMPT.format(
                alertname=labels.get("alertname", ""),
                severity=labels.get("severity", ""),
                startsAt=alert.get("startsAt", ""),
                summary=alert.get("annotations", {}).get("summary", ""),
                description=alert.get("annotations", {}).get("description", ""),
                labels=json.dumps(labels, sort_keys=True),
            ),
        }
        if started_in_last_hour() >= MAX_PER_HOUR:
            item["status"] = "skipped"
            item["report"] = f"Not investigated: {MAX_PER_HOUR} investigations already started in the last hour."
        investigations.insert(0, item)
        save()
    if item["status"] == "queued":
        work.put(item)
    print(f"{item['received']} {item['status']}: {item['alertname']}", flush=True)


def investigate(item):
    command = [
        "claude", "-p", item["prompt"],
        "--model", MODEL,
        # Only the MCP server in this file, not anything else it might find.
        "--strict-mcp-config", "--mcp-config", MCP_CONFIG,
        # The workspace's permissions. Claude Code ignores a folder's own
        # allow-list until someone trusts the folder interactively, which can't
        # happen here, so pass the same file explicitly.
        "--settings", f"{WORKSPACE}/.claude/settings.json",
        # Anything those settings don't allow is refused, not asked.
        "--permission-mode", "dontAsk",
        "--max-turns", MAX_TURNS,
        "--max-budget-usd", MAX_BUDGET_USD,
        "--output-format", "json",
    ]
    with lock:
        item.update(status="running", started_s=time.time())
        save()
    try:
        run = subprocess.run(command, cwd=WORKSPACE, capture_output=True, text=True, timeout=TIMEOUT_S)
        result = json.loads(run.stdout) if run.stdout.strip() else {}
        outcome = {
            "status": "done" if run.returncode == 0 and not result.get("is_error") else "failed",
            "report": result.get("result") or run.stderr[-2000:],
            "subtype": result.get("subtype"),
            "cost_usd": result.get("total_cost_usd"),
            "turns": result.get("num_turns"),
            "denied": [d.get("tool_name") for d in result.get("permission_denials") or []],
        }
    except subprocess.TimeoutExpired:
        outcome = {"status": "failed", "report": f"Stopped after {TIMEOUT_S} seconds."}
    except ValueError:
        outcome = {"status": "failed", "report": "Claude Code didn't return JSON."}
    with lock:
        item.update(outcome, seconds=round(time.time() - item["started_s"]))
        save()
    print(f"{item['alertname']}: {item['status']} in {item['seconds']}s, ${item.get('cost_usd')}", flush=True)


def worker():
    # One at a time: simpler to read, and it keeps the cost predictable.
    while True:
        investigate(work.get())


def card(item):
    facts = [f"fired {item['startsAt'][:19].replace('T', ' ')} UTC", item["status"]]
    if "seconds" in item:
        facts.append(f"{item['seconds']} s")
    if item.get("cost_usd") is not None:
        facts.append(f"${item['cost_usd']:.2f}")
    if item.get("turns"):
        facts.append(f"{item['turns']} turns")
    return (
        f"<section class='{html.escape(item['status'])}'><h2>{html.escape(item['alertname'])}</h2>"
        f"<p class='facts'>{html.escape(' · '.join(facts))}</p>"
        f"<pre>{html.escape(item.get('report') or 'Investigating…')}</pre></section>"
    )


PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Lab 5: AI investigations</title>
<meta http-equiv="refresh" content="10">
<style>
  body { margin:28px auto; max-width:900px; padding:0 20px; font:14px/1.5 system-ui, -apple-system, sans-serif; color:#1d1d1b; background:#f7f7f5; }
  h1 { margin:0 0 4px; font-size:20px; } p { margin:0 0 16px; color:#6b6b66; }
  section { background:#fff; border:1px solid #e3e2dc; border-radius:8px; padding:14px 18px; margin:0 0 14px; }
  h2 { margin:0; font-size:16px; } .facts { margin:2px 0 10px; font-size:13px; }
  pre { white-space:pre-wrap; margin:0; font:13px/1.5 ui-monospace, Menlo, monospace; }
  .failed h2, .skipped h2 { color:#b3261e; } .running h2, .queued h2 { color:#8a5a00; }
</style></head><body>
<h1>Lab 5: AI investigations</h1>
<p>One per alert that started firing, newest first. This page refreshes every 10 seconds.</p>
__CARDS__</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def send(self, status, body, content_type):
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/healthz":
            return self.send(200, "ok", "text/plain")
        with lock:
            items = [dict(item) for item in investigations]
        if self.path == "/api/investigations":
            return self.send(200, json.dumps(items), "application/json")
        if self.path == "/":
            cards = "".join(card(item) for item in items) or "<p>No alerts yet.</p>"
            return self.send(200, PAGE.replace("__CARDS__", cards), "text/html; charset=utf-8")
        return self.send(404, "not found", "text/plain")

    def do_POST(self):
        if self.path != "/webhook":
            return self.send(404, "not found", "text/plain")
        payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        for alert in payload.get("alerts", []):
            accept(alert)
        self.send(200, "ok", "text/plain")

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    # Investigations that were running when the pod stopped can't resume.
    for item in investigations:
        if item["status"] in ("queued", "running"):
            item.update(status="failed", report="The investigator restarted before this finished.")
    threading.Thread(target=worker, daemon=True).start()
    ThreadingHTTPServer(("", 8000), Handler).serve_forever()
