"""Small standard-library client for the lab, shared by the setup scripts."""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CREDENTIALS = Path(__file__).resolve().parent.parent / ".lab-credentials"
SIGNOZ_URL = "http://signoz.localhost:8080"
APP_URL = "http://app.localhost:8080"

# Ignore any HTTP proxy settings: everything here is on this machine.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def request(url, data=None, token=None, method=None, timeout=20):
    """Returns (status, parsed JSON or None). Status 0 means no connection."""
    headers = {"content-type": "application/json"}
    if token:
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
