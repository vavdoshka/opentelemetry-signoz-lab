#!/usr/bin/env python3
"""Creates a lab's SigNoz saved views from a JSON file, unless they already exist.

A saved view is a search kept in SigNoz's Logs or Traces explorer, under Views.
Each view has a fixed machine name, so a rerun finds it and leaves it alone.
SigNoz's home page ticks "Setup Saved Views" once any view exists.

Usage: create_saved_views.py SAVED_VIEWS_JSON
"""

import json
import sys
from pathlib import Path

from signoz_client import SIGNOZ_URL, request, session

URL = f"{SIGNOZ_URL}/api/v2/saved_views"


def existing_names(token, source):
    status, body = request(f"{URL}?source={source}", token=token)
    if status != 200:
        raise SystemExit(f"Could not list {source} saved views: HTTP {status} {json.dumps(body)[:300]}")
    views = body.get("data") or []
    return {view.get("name") for view in views}


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: create_saved_views.py SAVED_VIEWS_JSON")
    views = json.loads(Path(sys.argv[1]).read_text())
    token = session()
    if not token:
        raise SystemExit("No SigNoz login. Run make up first.")

    names = {}
    for view in views:
        source = view["source"]
        if source not in names:
            names[source] = existing_names(token, source)
        title = view["spec"]["displayName"]
        if view["name"] in names[source]:
            print(f"Saved view already exists: {title}")
            continue
        status, body = request(URL, view, token=token)
        if status not in (200, 201):
            raise SystemExit(f"SigNoz refused saved view {title}: HTTP {status} {json.dumps(body)[:300]}")
        print(f"Created saved view: {title} ({source})")


if __name__ == "__main__":
    main()
