#!/usr/bin/env python3
"""Creates or updates a SigNoz log pipeline from a JSON file.

SigNoz saves pipelines as one list, so posting a list without someone else's
pipeline deletes it. This keeps every other pipeline, and replaces only the one
with the same alias. SigNoz then sends the new list to its collectors.

Usage: create_log_pipeline.py PIPELINE_JSON
"""

import json
import sys
import time
from pathlib import Path

from signoz_client import SIGNOZ_URL, request, session

URL = f"{SIGNOZ_URL}/api/v1/logs/pipelines"
# What SigNoz accepts back. Its GET answer adds fields of its own.
POSTABLE = ("id", "orderId", "name", "alias", "description", "enabled", "filter", "config")


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: create_log_pipeline.py PIPELINE_JSON")
    ours = json.loads(Path(sys.argv[1]).read_text())
    token = session()
    if not token:
        raise SystemExit("No SigNoz login. Run make up first.")

    status, body = request(f"{URL}/latest", token=token)
    if status != 200:
        raise SystemExit(f"Could not read the pipelines: HTTP {status}")
    current = [{k: p[k] for k in POSTABLE if k in p} for p in body["data"]["pipelines"] or []]
    others = [p for p in current if p.get("alias") != ours["alias"]]
    existing = next((p for p in current if p.get("alias") == ours["alias"]), None)
    if existing and all(existing.get(k) == ours.get(k) for k in POSTABLE if k not in ("id", "orderId")):
        # Posting it again would make a version the collectors never confirm,
        # because their config doesn't change. It stays "in progress" for good.
        print(f"Log pipeline '{ours['name']}' is already up to date.")
        return
    if existing:
        # Keep its id and place, so SigNoz records an edit rather than a new pipeline.
        ours = {**ours, "id": existing["id"], "orderId": existing["orderId"]}
    else:
        ours = {**ours, "id": "", "orderId": len(others) + 1}
    pipelines = sorted(others + [ours], key=lambda p: p["orderId"])

    status, body = request(URL, {"pipelines": pipelines}, token=token)
    if status != 200:
        raise SystemExit(f"SigNoz refused the pipeline: HTTP {status} {json.dumps(body)[:300]}")
    version = body["data"]["version"]
    print(f"Saved log pipeline '{ours['name']}' as version {version}.")

    # SigNoz sends pipelines to its collectors over OpAMP. Until they apply them,
    # new logs pass through unparsed.
    deadline = time.time() + 120
    state = None
    while time.time() < deadline:
        _status, body = request(f"{URL}/latest", token=token)
        history = (body or {}).get("data", {}).get("history") or []
        state = next((str(h.get("deployStatus")).lower() for h in history if h.get("version") == version), None)
        if state == "deployed":
            print("SigNoz's collectors are using it.")
            return
        if state == "deploy_failed":
            raise SystemExit("SigNoz's collectors rejected it. See the Pipelines page in SigNoz.")
        time.sleep(5)
    raise SystemExit(f"Not applied by SigNoz's collectors after 2 minutes (status {state}).")


if __name__ == "__main__":
    main()
