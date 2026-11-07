#!/usr/bin/env python3
"""Creates or updates Lab 4's notification channel and alert rules."""

import json
from pathlib import Path

from signoz_client import SIGNOZ_URL, login, read_credentials, received_alerts, request, wait_for

ALERTS = Path(__file__).resolve().parent.parent / "labs/lab4-alerts/alerts.json"


def existing(token, path, key):
    status, result = request(f"{SIGNOZ_URL}{path}", token=token)
    if status != 200:
        raise SystemExit(f"Could not read {path} (HTTP {status}).")
    data = result["data"]
    items = data.get(key, []) if isinstance(data, dict) else data
    return items or []


def main():
    alerts = json.loads(ALERTS.read_text())
    credentials = read_credentials()
    token = login(credentials) if credentials else None
    if not token:
        raise SystemExit("Could not log in to SigNoz, so no alerts were created.")

    channel = alerts["channel"]
    if channel["displayName"] in json.dumps(existing(token, "/api/v2/notification_channels", "channels")):
        print(f"Channel already exists: {channel['displayName']}")
    else:
        status, result = request(f"{SIGNOZ_URL}/api/v2/notification_channels", channel, token)
        if status not in (200, 201):
            raise SystemExit(f"Could not create the channel (HTTP {status}): {json.dumps(result)[:400]}")
        print(f"Created channel: {channel['displayName']}")

    rules = existing(token, "/api/v2/rules", "rules")
    present = {rule["alert"]: rule["id"] for rule in rules}
    for rule in alerts["rules"]:
        name = rule["alert"]
        if name in present:
            status, result = request(f"{SIGNOZ_URL}/api/v2/rules/{present[name]}", rule, token, method="PUT")
        else:
            status, result = request(f"{SIGNOZ_URL}/api/v2/rules", rule, token)
        if status not in (200, 201, 204):
            raise SystemExit(f"Could not save rule {name} (HTTP {status}): {json.dumps(result)[:400]}")
        print(f"{'Updated' if name in present else 'Created'} rule: {name}")

    # The file is the source of truth, but only for rules this lab created.
    wanted = {rule["alert"] for rule in alerts["rules"]}
    for rule in rules:
        if rule["alert"] not in wanted and rule.get("labels", {}).get("lab") == "lab4":
            status, result = request(f"{SIGNOZ_URL}/api/v2/rules/{rule['id']}", token=token, method="DELETE")
            if status not in (200, 204):
                raise SystemExit(f"Could not remove rule {rule['alert']} (HTTP {status}): {json.dumps(result)[:400]}")
            print(f"Removed rule: {rule['alert']}")

    # A created channel proves nothing, so send one through it and see that it arrives.
    # This can take a few tries, because a new Service isn't routable the moment its
    # pod is ready.
    def test_notification_arrives():
        before = len(received_alerts())
        status, _ = request(f"{SIGNOZ_URL}/api/v2/notification_channels/test", {"config": channel["config"]}, token, timeout=40)
        return status in (200, 204) and len(received_alerts()) > before

    wait_for("a test notification at the sink", test_notification_arrives, timeout=60, interval=3)


if __name__ == "__main__":
    main()
