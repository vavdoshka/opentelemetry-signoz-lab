"""Stands in for Slack or PagerDuty, so you can see exactly what SigNoz sends.

SigNoz's webhook channel posts Alertmanager's payload to POST /webhook. This keeps
the most recent alerts in memory and shows them at /, or as JSON at /api/alerts.
Standard library only.
"""

import html
import json
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

received = deque(maxlen=200)


def row(alert):
    labels = alert["labels"]
    return (
        f"<tr><td>{html.escape(alert['received'])}</td><td class='{html.escape(alert['status'])}'>"
        f"{html.escape(alert['status'])}</td><td>{html.escape(labels.get('alertname', ''))}</td>"
        f"<td>{html.escape(labels.get('severity', ''))}</td>"
        f"<td>{html.escape(alert['annotations'].get('description', ''))}</td></tr>"
    )


PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Lab 4: alert sink</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 32 32%22 role=%22img%22 aria-label=%22Spans in a trace%2C the last one failing%22%3E%3Crect width=%2232%22 height=%2232%22 rx=%227%22 fill=%22%231f62b5%22/%3E%3Crect x=%225%22 y=%227%22 width=%2222%22 height=%224.5%22 rx=%222.25%22 fill=%22%23fff%22/%3E%3Crect x=%229%22 y=%2214%22 width=%2213%22 height=%224.5%22 rx=%222.25%22 fill=%22%23fff%22/%3E%3Crect x=%2214%22 y=%2221%22 width=%2213%22 height=%224.5%22 rx=%222.25%22 fill=%22%23ffa26e%22/%3E%3C/svg%3E">
<meta http-equiv="refresh" content="5">
<style>
  body { margin:28px; font:14px/1.45 system-ui, -apple-system, sans-serif; color:#1d1d1b; background:#f7f7f5; }
  h1 { margin:0 0 4px; font-size:20px; } p { margin:0 0 16px; color:#6b6b66; }
  table { border-collapse:collapse; width:100%; background:#fff; }
  th, td { text-align:left; padding:8px 10px; border:1px solid #e3e2dc; vertical-align:top; }
  .firing { color:#b3261e; font-weight:600; } .resolved { color:#1f7a4d; font-weight:600; }
</style></head><body>
<h1>Lab 4: alert sink</h1>
<p>Notifications SigNoz has sent here, newest first. This page refreshes every 5 seconds.</p>
<table><thead><tr><th>Received</th><th>Status</th><th>Alert</th><th>Severity</th><th>Description</th></tr></thead>
<tbody>__ROWS__</tbody></table></body></html>"""


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
        if self.path == "/api/alerts":
            return self.send(200, json.dumps(list(received)), "application/json")
        if self.path == "/":
            rows = "".join(row(alert) for alert in received) or "<tr><td colspan='5'>Nothing yet.</td></tr>"
            return self.send(200, PAGE.replace("__ROWS__", rows), "text/html; charset=utf-8")
        return self.send(404, "not found", "text/plain")

    def do_POST(self):
        if self.path != "/webhook":
            return self.send(404, "not found", "text/plain")
        payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        now = time.strftime("%H:%M:%S", time.gmtime())
        for alert in payload.get("alerts", []):
            received.appendleft(
                {
                    "received": now,
                    "received_ms": int(time.time() * 1000),
                    "status": alert.get("status", ""),
                    "labels": alert.get("labels", {}),
                    "annotations": alert.get("annotations", {}),
                    "startsAt": alert.get("startsAt", ""),
                    "endsAt": alert.get("endsAt", ""),
                }
            )
            print(f"{now} {alert.get('status')} {alert.get('labels', {}).get('alertname')}")
        self.send(200, "ok", "text/plain")

    def log_message(self, *_args):
        pass  # Probes would otherwise fill the log.


ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
