#!/usr/bin/env python3
"""Creates Lab 2's SigNoz dashboard, unless it already exists."""

import json
from pathlib import Path

from signoz_client import SIGNOZ_URL, login, read_credentials, request

DASHBOARD = Path(__file__).resolve().parent.parent / "labs/lab2-custom-dimensions/dashboard.json"


def main():
    dashboard = json.loads(DASHBOARD.read_text())
    name = dashboard["spec"]["display"]["name"]
    credentials = read_credentials()
    token = login(credentials) if credentials else None
    if not token:
        raise SystemExit("Could not log in to SigNoz, so the dashboard was not created.")

    status, existing = request(f"{SIGNOZ_URL}/api/v2/dashboards", token=token)
    if status != 200:
        raise SystemExit(f"Could not list dashboards (HTTP {status}).")
    if name in json.dumps(existing["data"]):
        print(f"Dashboard already exists: {name}")
        return

    status, result = request(f"{SIGNOZ_URL}/api/v2/dashboards", dashboard, token)
    if status not in (200, 201):
        raise SystemExit(f"Could not create the dashboard (HTTP {status}): {json.dumps(result)[:300]}")
    print(f"Created dashboard: {name}")


if __name__ == "__main__":
    main()
