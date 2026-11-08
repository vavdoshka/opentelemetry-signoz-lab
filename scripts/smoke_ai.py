#!/usr/bin/env python3
"""Proves Lab 5's plumbing works, without paying for an investigation.

- The MCP server answers, lists its tools, can read, and is refused writes.
- The AI's Kubernetes account can read pods and can't read Secrets.
- The investigator is up, and the chosen rules send it their alerts.
- If a Claude login is set up, Claude Code in the investigator pod can use it.
  That costs one short answer, about a cent.

Usage: smoke_ai.py KUBE_CONTEXT
"""

import json
import subprocess
import sys
from pathlib import Path

from create_alerts import existing
from signoz_client import SIGNOZ_URL, request, session, wait_for

MCP_URL = "http://mcp.localhost:8080/mcp"
# MCP's HTTP transport requires a client to accept both.
MCP_HEADERS = {"accept": "application/json, text/event-stream"}
LAB5_URL = "http://lab5.localhost:8080"
ROUTES = Path(__file__).resolve().parent.parent / "labs/lab5-ai/investigate.json"


def mcp(method, params=None):
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    status, result = request(MCP_URL, body, timeout=60, headers=MCP_HEADERS)
    if status != 200 or not result or "result" not in result:
        raise SystemExit(f"MCP {method} failed (HTTP {status}): {json.dumps(result)[:300]}")
    return result["result"]


def call(tool, arguments):
    result = mcp("tools/call", {"name": tool, "arguments": arguments})
    return bool(result.get("isError")), "".join(part.get("text", "") for part in result.get("content", []))


def kubectl(context, *args):
    return subprocess.run(["kubectl", "--context", context, *args], capture_output=True, text=True)


def main():
    context = sys.argv[1]

    wait_for("the MCP server", lambda: request(MCP_URL, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, timeout=10, headers=MCP_HEADERS)[0] == 200, timeout=120)
    tools = [tool["name"] for tool in mcp("tools/list")["tools"]]
    print(f"  ok: the MCP server offers {len(tools)} tools")
    failed, text = call("signoz_list_services", {"timeRange": "1h"})
    if failed:
        raise SystemExit(f"Reading through MCP failed: {text[:300]}")
    print("  ok: it can read SigNoz")
    failed, text = call("signoz_create_dashboard", {"title": "Lab 5 smoke test, should be refused", "layout": [], "widgets": []})
    if not failed or "403" not in text:
        raise SystemExit(f"Creating a dashboard through MCP wasn't refused with 403: {text[:300]}")
    print("  ok: SigNoz refuses its writes (403)")

    reader = ["--as", "system:serviceaccount:lab5:ai-reader"]
    if kubectl(context, *reader, "-n", "lab3", "get", "pods").returncode != 0:
        raise SystemExit("The AI's Kubernetes account can't list pods.")
    if kubectl(context, *reader, "-n", "lab5", "get", "secrets").returncode == 0:
        raise SystemExit("The AI's Kubernetes account can read Secrets. It shouldn't.")
    print("  ok: its Kubernetes account can read pods, and not Secrets")

    wait_for("the investigator", lambda: request(f"{LAB5_URL}/api/investigations")[0] == 200, timeout=120)
    token = session()
    wanted = {item["rule"] for item in json.loads(ROUTES.read_text())["investigate"]}
    routed = set()
    for rule in existing(token, "/api/v2/rules", "rules"):
        channels = {c for threshold in rule["condition"]["thresholds"]["spec"] for c in threshold.get("channels", [])}
        if "Lab 5 investigator" in channels:
            routed.add(rule["alert"])
    if routed != wanted:
        raise SystemExit(f"Rules sending to the investigator: {sorted(routed)}. Expected: {sorted(wanted)}.")
    print(f"  ok: {len(routed)} rules send their alerts to the investigator")

    if kubectl(context, "-n", "lab5", "get", "secret", "claude-auth").returncode != 0:
        print("No Claude login (.lab-ai-credentials), so the AI itself wasn't tested.")
        return
    run = kubectl(context, "-n", "lab5", "exec", "deploy/investigator", "--", "claude", "-p", "Reply with the single word: ok",
                  "--model", "sonnet", "--max-turns", "1", "--output-format", "json")
    try:
        answer = json.loads(run.stdout)
    except ValueError:
        raise SystemExit(f"Claude Code in the investigator failed: {(run.stderr or run.stdout)[-400:]}")
    if answer.get("is_error") or "ok" not in (answer.get("result") or "").lower():
        raise SystemExit(f"Claude Code in the investigator failed: {json.dumps(answer)[:400]}")
    print(f"  ok: Claude Code in the investigator can log in (that answer cost ${answer.get('total_cost_usd', 0):.3f})")
    print("Smoke test passed: Lab 5's MCP server, access and investigator work.")


if __name__ == "__main__":
    main()
