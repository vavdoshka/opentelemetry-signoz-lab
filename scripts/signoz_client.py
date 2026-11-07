"""Small standard-library client for the lab, shared by the setup scripts.

Set SIGNOZ_URL and SIGNOZ_API_KEY to point the dashboard and alert scripts at
any SigNoz, using a service account's key instead of the lab's login.
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CREDENTIALS = Path(__file__).resolve().parent.parent / ".lab-credentials"
SIGNOZ_URL = os.environ.get("SIGNOZ_URL", "http://signoz.localhost:8080").rstrip("/")
API_KEY = os.environ.get("SIGNOZ_API_KEY")
LAB3_URL = "http://lab3.localhost:8080"
LAB4_URL = "http://lab4.localhost:8080"
LABS = {
    "1": {"url": "http://lab1.localhost:8080", "frontend": "lab1-frontend", "backend": "lab1-backend"},
    "2": {"url": "http://lab2.localhost:8080", "frontend": "frontend", "backend": "backend"},
}

# Ignore any HTTP proxy settings: the lab is all on this machine.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def request(url, data=None, token=None, method=None, timeout=20):
    """Returns (status, parsed JSON or None). Status 0 means no connection."""
    headers = {"content-type": "application/json"}
    if API_KEY:
        headers["SigNoz-Api-Key"] = API_KEY
    elif token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with _opener.open(req, timeout=timeout) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read()
    except OSError:
        return 0, None
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, None


def read_credentials():
    if not CREDENTIALS.exists():
        return None
    pairs = (line.strip().split("=", 1) for line in CREDENTIALS.read_text().splitlines() if "=" in line)
    return dict(pairs)


def login(credentials):
    """Returns an access token, or None if the login is refused."""
    query = urllib.parse.urlencode({"email": credentials["SIGNOZ_EMAIL"], "ref": SIGNOZ_URL})
    status, context = request(f"{SIGNOZ_URL}/api/v2/sessions/context?{query}")
    if status != 200 or not context["data"]["orgs"]:
        return None
    status, session = request(
        f"{SIGNOZ_URL}/api/v2/sessions/email_password",
        {
            "email": credentials["SIGNOZ_EMAIL"],
            "password": credentials["SIGNOZ_PASSWORD"],
            "orgId": context["data"]["orgs"][0]["id"],
        },
    )
    return session["data"]["accessToken"] if status == 200 else None


def session():
    """Returns what request() needs as its token, or None if there's no way in."""
    if API_KEY:
        return API_KEY
    credentials = read_credentials()
    return login(credentials) if credentials else None


def query(token, signal, spec, request_type, minutes=10):
    """Runs one SigNoz query and returns its first result, or None."""
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


def count(token, signal, expression, minutes=10):
    """Counts matching spans or logs."""
    spec = {"aggregations": [{"expression": "count()"}], "filter": {"expression": expression}}
    result = query(token, signal, spec, "scalar", minutes)
    try:
        return result["data"][0][-1]
    except (KeyError, IndexError, TypeError):
        return 0


def metric_exists(token, name, expression="", minutes=10):
    """True if the metric has data points, optionally filtered."""
    spec = {
        # "latest" works for gauges and counters. "rate" returns nothing for an idle counter.
        "aggregations": [{"metricName": name, "timeAggregation": "latest", "spaceAggregation": "sum"}],
        "stepInterval": 60,
    }
    if expression:
        spec["filter"] = {"expression": expression}
    result = query(token, "metrics", spec, "time_series", minutes)
    return bool(result and any(item.get("series") for item in result.get("aggregations") or []))


def fire(lab, scenario):
    """Runs a scenario. Returns the response status and body."""
    return request(f"{LABS[lab]['url']}/api/scenario/{scenario}", {}, timeout=30)


def received_alerts():
    """What Lab 4's sink has received, newest first."""
    status, alerts = request(f"{LAB4_URL}/api/alerts")
    return alerts if status == 200 else []


def wait_for(description, check, timeout, interval=5):
    """Calls check() until it returns something truthy, or raises at the timeout."""
    print(f"Waiting for {description}...", flush=True)
    deadline = time.monotonic() + timeout
    while True:
        result = check()
        if result:
            print(f"  ok: {description}", flush=True)
            return result
        if time.monotonic() > deadline:
            raise SystemExit(f"Timed out after {timeout}s waiting for {description}")
        time.sleep(interval)
