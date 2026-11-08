#!/usr/bin/env python3
"""Local server for the telemetry tutorial. Standard library only.

    python3 tutorial/server.py        then open http://127.0.0.1:8765

It does two jobs:

  1. Serves the pages in this folder.
  2. Bridges to the lab under /live/, because the test app sends no CORS
     headers and SigNoz needs a login. The browser only ever talks to this
     server, and the SigNoz password never leaves it.

The bridge is deliberately narrow. It can run the known scenarios on any lab,
start and stop each lab's load generator, read the alerts Lab 4 received, and
run read-only searches. It cannot reach any other path on the apps or on SigNoz. Searches are limited to
the saved catalogue in data/queries.json, a lookup of one trace by ID, and a
fixed search for the trace of a scenario this bridge has just fired.

That last search exists because Lab 1's app knows nothing about tracing, so its
API returns no trace ID. The bridge sends scenarios with its own User-Agent, so
it can tell its own request from load generator traffic on the same route.

Each lab is checked on its own. `make up` deploys only Lab 1, so Lab 1 must keep
working when the later labs are not there. If a lab is down, pages still load and show the
saved examples.

Optional environment variables: TUTORIAL_PORT, TUTORIAL_LAB1_URL,
TUTORIAL_LAB2_URL, TUTORIAL_LAB3_URL, TUTORIAL_LAB4_URL, TUTORIAL_SIGNOZ_URL.
"""

import http.client
import json
import mimetypes
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
CREDENTIALS = HERE.parent / ".lab-credentials"
HOST = "127.0.0.1"
PORT = int(os.environ.get("TUTORIAL_PORT", "8765"))
SIGNOZ_URL = os.environ.get("TUTORIAL_SIGNOZ_URL", "http://signoz.localhost:8080").rstrip("/")
ALERT_SINK_URL = os.environ.get("TUTORIAL_LAB4_URL", "http://lab4.localhost:8080").rstrip("/")
REPORTS = HERE.parent / "labs/lab5-ai/reports"

LABS = {
    "lab1": {
        "name": "Lab 1",
        "url": os.environ.get("TUTORIAL_LAB1_URL", "http://lab1.localhost:8080").rstrip("/"),
        "frontend": "lab1-frontend",
        "start": "make up",
    },
    "lab2": {
        "name": "Lab 2",
        "url": os.environ.get("TUTORIAL_LAB2_URL", "http://lab2.localhost:8080").rstrip("/"),
        "frontend": "frontend",
        "start": "make lab2",
    },
    "lab3": {
        "name": "Lab 3",
        "url": os.environ.get("TUTORIAL_LAB3_URL", "http://lab3.localhost:8080").rstrip("/"),
        "frontend": "lab3-workload",
        "start": "make lab3",
    },
}
SCENARIOS = {
    "order", "list", "slow", "bad_input", "crash", "backend_500", "timeout",
    "slow_query", "db_error", "cpu_burn", "log_burst", "slow_item", "free_orders", "cache_miss",
    "throttle", "oom", "liveness", "disk", "api_flood", "api_denied",
}
LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
MAX_BURN_SECONDS = 120
STATIC_TYPES = {".html", ".css", ".js", ".json", ".png", ".svg", ".md"}
TRACE_ID = re.compile(r"^[0-9a-f]{32}$")
TRACE_LOOKBACK_MINUTES = 6 * 60
# Marks scenarios sent from here. A span records it as http.user_agent.
USER_AGENT = "telemetry-tutorial"
# A trace is searched for from just before the scenario was fired, in case the
# clock inside the cluster is slightly behind this one.
CLOCK_SLACK_MS = 2000
UNREACHABLE = (urllib.error.URLError, http.client.HTTPException, OSError)

# Everything here is on this machine, so ignore any HTTP proxy settings.
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http_call(method, url, body=None, headers=None, timeout=20):
    """Return (status, parsed JSON or text). Raises URLError if unreachable."""
    data = None
    all_headers = {"Accept": "application/json", "User-Agent": USER_AGENT, **(headers or {})}
    if body is not None:
        data = json.dumps(body).encode()
        all_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=all_headers, method=method)
    try:
        with opener.open(request, timeout=timeout) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read()
    text = raw.decode("utf-8", "replace")
    try:
        return status, json.loads(text)
    except ValueError:
        return status, text


class SigNozSession:
    """Logs in with .lab-credentials and keeps the token in memory only."""

    TOKEN_LIFETIME = 20 * 60

    def __init__(self):
        self.token = None
        self.expires = 0.0
        self.lock = threading.Lock()

    @staticmethod
    def credentials():
        values = {}
        if CREDENTIALS.exists():
            for line in CREDENTIALS.read_text().splitlines():
                key, separator, value = line.partition("=")
                if separator:
                    values[key.strip()] = value.strip().strip("'\"")
        return values

    def available(self):
        values = self.credentials()
        return bool(values.get("SIGNOZ_EMAIL") and values.get("SIGNOZ_PASSWORD"))

    def login(self):
        values = self.credentials()
        email = values["SIGNOZ_EMAIL"]
        query = urllib.parse.urlencode({"email": email, "ref": SIGNOZ_URL})
        _, context = http_call("GET", f"{SIGNOZ_URL}/api/v2/sessions/context?{query}", timeout=10)
        org_id = context["data"]["orgs"][0]["id"]
        _, session = http_call(
            "POST",
            f"{SIGNOZ_URL}/api/v2/sessions/email_password",
            {"email": email, "password": values["SIGNOZ_PASSWORD"], "orgId": org_id},
            timeout=10,
        )
        self.token = session["data"]["accessToken"]
        self.expires = time.time() + self.TOKEN_LIFETIME

    def post(self, path, body):
        with self.lock:
            if not self.token or time.time() > self.expires:
                self.login()
            token = self.token
        status, result = http_call(
            "POST", SIGNOZ_URL + path, body, {"Authorization": f"Bearer {token}"}, timeout=30
        )
        if status == 401:
            with self.lock:
                self.login()
                token = self.token
            status, result = http_call(
                "POST", SIGNOZ_URL + path, body, {"Authorization": f"Bearer {token}"}, timeout=30
            )
        return status, result


signoz = SigNozSession()


def query_body(spec, request_type, minutes):
    end = int(time.time() * 1000)
    return {
        "schemaVersion": "v1",
        "start": end - minutes * 60_000,
        "end": end,
        "requestType": request_type,
        "compositeQuery": {"queries": [{"type": "builder_query", "spec": spec}]},
        "formatOptions": {"formatTableResultForUI": False, "fillGaps": False},
        "variables": {},
    }


def catalogue():
    with open(HERE / "data" / "queries.json") as handle:
        return {item["id"]: item for item in json.load(handle)["queries"]}


def run_catalogue_query(query_id):
    item = catalogue().get(query_id)
    if item is None:
        return 404, {"error": f"unknown query {query_id}"}
    body = query_body(item["spec"], item["requestType"], item["liveMinutes"])
    status, result = signoz.post("/api/v5/query_range", body)
    return status, {"minutes": item["liveMinutes"], "result": result}


def rows_of(response):
    try:
        return response["data"]["data"]["results"][0].get("rows") or []
    except (KeyError, IndexError, TypeError):
        return []


def find_trace(lab_id, scenario, since_ms):
    """The trace of a scenario this bridge fired, or None if it has not arrived.

    Lab 1's API returns no trace ID, so this asks SigNoz instead. It is read-only
    and fixed: `lab_id` and `scenario` are checked against known names first.
    """
    expression = (
        f"service.name = '{LABS[lab_id]['frontend']}' "
        f"AND http.target = '/api/scenario/{scenario}' "
        f"AND http.user_agent = '{USER_AGENT}'"
    )
    spec = {
        "name": "A",
        "signal": "traces",
        "filter": {"expression": expression},
        "limit": 1,
        "order": [{"key": {"name": "timestamp"}, "direction": "desc"}],
        "selectFields": [{"name": "name", "fieldContext": "span"}],
    }
    body = query_body(spec, "raw", 0)
    body["start"] = since_ms - CLOCK_SLACK_MS
    body["end"] += 60_000
    status, result = signoz.post("/api/v5/query_range", body)
    if status != 200:
        return status, {"error": "trace search failed"}
    rows = rows_of(result)
    return 200, {"trace_id": rows[0]["data"]["trace_id"] if rows else None, "search": expression}


def lookup_trace(trace_id):
    """Spans and logs for one trace, for the panel under each live button."""
    fields = [("service.name", "resource")] + [
        (name, "span")
        for name in (
            "name", "duration_nano", "response_status_code", "has_error",
            "kind_string", "parent_span_id", "status_code_string",
        )
    ] + [
        (name, "attribute")
        for name in ("db.statement", "order.item", "order.total", "order.coupon", "cache.hit")
    ]
    span_spec = {
        "name": "A",
        "signal": "traces",
        "filter": {"expression": f"trace_id = '{trace_id}'"},
        "limit": 100,
        "order": [{"key": {"name": "timestamp"}, "direction": "asc"}],
        "selectFields": [{"name": n, "fieldContext": c} for n, c in fields],
    }
    log_spec = {
        "name": "A",
        "signal": "logs",
        "filter": {"expression": f"trace_id = '{trace_id}'"},
        "limit": 12,
        "order": [{"key": {"name": "timestamp"}, "direction": "asc"}],
    }
    status, spans = signoz.post(
        "/api/v5/query_range", query_body(span_spec, "raw", TRACE_LOOKBACK_MINUTES)
    )
    if status != 200:
        return status, {"error": "trace lookup failed"}
    _, logs = signoz.post(
        "/api/v5/query_range", query_body(log_spec, "raw", TRACE_LOOKBACK_MINUTES)
    )
    return 200, {
        "spans": [
            {
                "start": row["data"].get("timestamp"),
                "service": row["data"].get("service.name"),
                "name": row["data"].get("name"),
                "kind": row["data"].get("kind_string"),
                "status": row["data"].get("status_code_string"),
                "http": row["data"].get("response_status_code"),
                "duration_nano": row["data"].get("duration_nano"),
                "parent": row["data"].get("parent_span_id"),
                "span_id": row["data"].get("span_id"),
                "has_error": row["data"].get("has_error"),
                "sql": row["data"].get("db.statement") or "",
                "order_item": row["data"].get("order.item") or "",
                "order_total": row["data"].get("order.total"),
                "order_coupon": row["data"].get("order.coupon") or "",
                "cache_hit": row["data"].get("cache.hit"),
            }
            for row in rows_of(spans)
        ],
        "logs": [
            {
                "ts": row.get("timestamp"),
                "service": (row["data"].get("resources_string") or {}).get("service.name", ""),
                "severity": row["data"].get("severity_text"),
                "body": (row["data"].get("body") or "")[:200],
                "attrs": log_attributes(row["data"]),
            }
            for row in rows_of(logs)
        ],
    }


def log_attributes(data):
    """The business fields an app passed through logging's extra=, if any."""
    values = {**(data.get("attributes_string") or {}), **(data.get("attributes_number") or {})}
    return {key: value for key, value in sorted(values.items()) if key.startswith("order.")}


def one_lab_status(lab_id):
    lab = LABS[lab_id]
    up, load = False, None
    try:
        status, result = http_call("GET", f"{lab['url']}/api/load", timeout=2)
        up = status == 200 and isinstance(result, dict)
        load = result if up else None
    except UNREACHABLE:
        pass
    return {"name": lab["name"], "up": up, "url": lab["url"], "start": lab["start"], "load": load}


def lab_status():
    signoz_up = False
    try:
        status, result = http_call("GET", f"{SIGNOZ_URL}/api/v1/health", timeout=2)
        signoz_up = status == 200 and isinstance(result, dict) and result.get("status") == "ok"
    except UNREACHABLE:
        pass
    return {
        "labs": {lab_id: one_lab_status(lab_id) for lab_id in LABS},
        "signoz": {"up": signoz_up, "url": SIGNOZ_URL, "queries": signoz_up and signoz.available()},
    }


def clean_scenario_body(name, body):
    """Keep only the parameters each scenario understands, within safe limits."""
    if name == "cpu_burn":
        seconds = float(body.get("seconds", 10))
        return {"seconds": max(1.0, min(seconds, MAX_BURN_SECONDS))}
    if name == "log_burst":
        level = str(body.get("level", "INFO")).upper()
        return {
            "count": max(1, min(int(body.get("count", 20)), 1000)),
            "level": level if level in LOG_LEVELS else "INFO",
        }
    if name == "throttle":
        return {"seconds": max(10, min(int(body.get("seconds", 120)), 300))}
    return {}


class Handler(BaseHTTPRequestHandler):
    server_version = "TelemetryTutorial/1.0"

    def log_message(self, format, *args):
        sys.stderr.write(f"{self.log_date_time_string()} {format % args}\n")

    def send_json(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            parsed = json.loads(self.rfile.read(length))
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def allowed_origin(self):
        """Only pages served from here may use the bridge."""
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            return False
        origin = self.headers.get("Origin")
        if origin:
            parsed = urllib.parse.urlparse(origin)
            return parsed.hostname in ("127.0.0.1", "localhost") and parsed.port == PORT
        return True

    def live(self, method, path, query):
        if not self.allowed_origin():
            return self.send_json(403, {"error": "this bridge only serves its own pages"})
        try:
            self.route_live(method, path, query)
        except UNREACHABLE + (KeyError, TypeError, ValueError) as error:
            self.send_json(502, {"error": "lab unavailable", "detail": type(error).__name__})

    def run_scenario(self, lab_id, name):
        body = clean_scenario_body(name, self.read_body())
        started = time.time()
        status, result = http_call(
            "POST",
            f"{LABS[lab_id]['url']}/api/scenario/{name}",
            body,
            timeout=body.get("seconds", 0) + 20,
        )
        return self.send_json(
            200,
            {
                "lab": lab_id,
                "scenario": name,
                "sent": body,
                "http": status,
                "fired_ms": int(started * 1000),
                "wall_ms": round((time.time() - started) * 1000),
                "response": result,
            },
        )

    def run_load(self, method, lab_id):
        url = f"{LABS[lab_id]['url']}/api/load"
        if method == "POST":
            body = self.read_body()
            config = {
                "rps": max(0.5, min(float(body.get("rps", 5)), 20)),
                "error_pct": max(0, min(int(body.get("error_pct", 10)), 100)),
            }
            return self.send_json(*http_call("POST", url, config, timeout=5))
        return self.send_json(*http_call(method, url, timeout=5))

    def route_live(self, method, path, query):
        parts = path.strip("/").split("/")[1:]
        if method == "GET" and parts == ["status"]:
            return self.send_json(200, lab_status())
        lab_id = parts[1] if len(parts) >= 2 else None
        if parts[:1] == ["scenario"] and len(parts) == 3 and method == "POST":
            if lab_id not in LABS or parts[2] not in SCENARIOS:
                return self.send_json(404, {"error": "unknown lab or scenario"})
            return self.run_scenario(lab_id, parts[2])
        if parts[:1] == ["find"] and len(parts) == 3 and method == "GET":
            if lab_id not in LABS or parts[2] not in SCENARIOS:
                return self.send_json(404, {"error": "unknown lab or scenario"})
            since = query.get("since", [""])[0]
            if not since.isdigit():
                return self.send_json(400, {"error": "since must be a time in milliseconds"})
            if not signoz.available():
                return self.send_json(503, {"error": ".lab-credentials not found"})
            return self.send_json(*find_trace(lab_id, parts[2], int(since)))
        if method == "GET" and parts == ["investigations"]:
            # What `make investigate` has saved, newest first.
            files = sorted(REPORTS.glob("*.json"), reverse=True)[:5] if REPORTS.exists() else []
            return self.send_json(200, [json.loads(path.read_text()) for path in files])
        if method == "GET" and parts == ["alerts"]:
            try:
                return self.send_json(*http_call("GET", f"{ALERT_SINK_URL}/api/alerts", timeout=3))
            except UNREACHABLE:
                return self.send_json(503, {"error": "Lab 4 is not running. Start it with: make lab4"})
        if parts[:1] == ["load"] and len(parts) == 2 and method in ("GET", "POST", "DELETE"):
            if lab_id not in LABS:
                return self.send_json(404, {"error": "unknown lab"})
            return self.run_load(method, lab_id)
        if parts[:1] == ["query"] and len(parts) == 2 and method == "POST":
            if not signoz.available():
                return self.send_json(503, {"error": ".lab-credentials not found"})
            return self.send_json(*run_catalogue_query(parts[1]))
        if parts[:1] == ["trace"] and len(parts) == 2 and method == "GET":
            if not TRACE_ID.match(parts[1]):
                return self.send_json(400, {"error": "a trace ID is 32 hex characters"})
            if not signoz.available():
                return self.send_json(503, {"error": ".lab-credentials not found"})
            return self.send_json(*lookup_trace(parts[1]))
        return self.send_json(404, {"error": "not a bridge route"})

    def serve_static(self, path):
        relative = urllib.parse.unquote(path).lstrip("/") or "index.html"
        if relative.endswith("/"):
            relative += "index.html"
        target = (HERE / relative).resolve()
        if (
            HERE not in target.parents
            or target.suffix not in STATIC_TYPES
            or not target.is_file()
        ):
            return self.send_json(404, {"error": "not found"})
        data = target.read_bytes()
        kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def handle_request(self, method):
        url = urllib.parse.urlparse(self.path)
        path = url.path
        if path == "/live" or path.startswith("/live/"):
            return self.live(method, path, urllib.parse.parse_qs(url.query))
        if method == "GET":
            return self.serve_static(path)
        return self.send_json(405, {"error": "method not allowed"})

    def do_GET(self):
        self.handle_request("GET")

    def do_POST(self):
        self.handle_request("POST")

    def do_DELETE(self):
        self.handle_request("DELETE")


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Telemetry tutorial: http://{HOST}:{PORT}", flush=True)
    status = lab_status()
    for lab in status["labs"].values():
        state = "up" if lab["up"] else f"not reachable, start it with: {lab['start']}"
        print(f"  {lab['name']}:    {state} ({lab['url']})", flush=True)
    print(f"  SigNoz:   {'up' if status['signoz']['up'] else 'not reachable'} ({SIGNOZ_URL})", flush=True)
    if not all(lab["up"] for lab in status["labs"].values()) or not status["signoz"]["up"]:
        print("  Live buttons for anything not reachable will be off. Saved examples still work.", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
