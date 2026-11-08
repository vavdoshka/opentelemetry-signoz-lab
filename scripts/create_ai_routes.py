#!/usr/bin/env python3
"""Sends some of Lab 4's alerts to Lab 5's investigator as well.

Creates the "Lab 5 investigator" webhook channel, then adds it next to
"Lab 4 webhook" on the rules listed in labs/lab5-ai/investigate.json, and
removes it from every other rule. The rules themselves still come from
labs/lab4-alerts/alerts.json.

make lab4 rewrites the rules from that file, which drops this channel, so
scripts/deploy-alerts.sh runs this again when Lab 5 is deployed.
"""

import copy
import json
from pathlib import Path

from create_alerts import ALERTS, existing
from signoz_client import SIGNOZ_URL, request, session

ROUTES = Path(__file__).resolve().parent.parent / "labs/lab5-ai/investigate.json"


def with_channel(rule, channel, wanted):
    rule = copy.deepcopy(rule)
    for threshold in rule["condition"]["thresholds"]["spec"]:
        channels = [c for c in threshold["channels"] if c != channel]
        threshold["channels"] = channels + [channel] if wanted else channels
    return rule


def main():
    routes = json.loads(ROUTES.read_text())
    rules = json.loads(ALERTS.read_text())["rules"]
    token = session()
    if not token:
        raise SystemExit("Could not log in to SigNoz.")

    channel = routes["channel"]
    if channel["displayName"] in json.dumps(existing(token, "/api/v2/notification_channels", "channels")):
        print(f"Channel already exists: {channel['displayName']}")
    else:
        status, result = request(f"{SIGNOZ_URL}/api/v2/notification_channels", channel, token)
        if status not in (200, 201):
            raise SystemExit(f"Could not create the channel (HTTP {status}): {json.dumps(result)[:400]}")
        print(f"Created channel: {channel['displayName']}")

    investigate = {item["rule"] for item in routes["investigate"]}
    unknown = investigate - {rule["alert"] for rule in rules}
    if unknown:
        raise SystemExit(f"Not in Lab 4's rules: {', '.join(sorted(unknown))}")
    present = {rule["alert"]: rule["id"] for rule in existing(token, "/api/v2/rules", "rules")}
    for rule in rules:
        name = rule["alert"]
        if name not in present:
            raise SystemExit(f"Rule {name} doesn't exist yet. Run make lab4 first.")
        body = with_channel(rule, channel["displayName"], name in investigate)
        status, result = request(f"{SIGNOZ_URL}/api/v2/rules/{present[name]}", body, token, method="PUT")
        if status not in (200, 204):
            raise SystemExit(f"Could not update rule {name} (HTTP {status}): {json.dumps(result)[:400]}")
        print(f"{'Investigated' if name in investigate else 'Not investigated'}: {name}")


if __name__ == "__main__":
    main()
