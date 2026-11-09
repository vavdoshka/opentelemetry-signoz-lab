#!/usr/bin/env python3
"""Proves Lab 6's cluster side works, with no AI and no cost.

- The MCP server answers, lists its tools, can read, and is refused writes.
- The AI's Kubernetes account can read pods and can't read Secrets.

Usage: smoke_ai.py KUBE_CONTEXT
"""

import json
import subprocess
import sys
import time

from signoz_client import request, wait_for

MCP_URL = "http://mcp.localhost:8080/mcp"
# MCP's HTTP transport requires a client to accept both.
MCP_HEADERS = {"accept": "application/json, text/event-stream"}


def mcp(method, params=None):
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    # Just after a restart, the ingress can briefly route to the old pod.
    for _ in range(12):
        status, result = request(MCP_URL, body, timeout=60, headers=MCP_HEADERS)
        if status == 200 and result and "result" in result:
            return result["result"]
        time.sleep(5)
    raise SystemExit(f"MCP {method} failed (HTTP {status}): {json.dumps(result)[:300]}")


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
    failed, text = call("signoz_create_dashboard", {"title": "Lab 6 smoke test, should be refused", "layout": [], "widgets": []})
    if not failed or "403" not in text:
        raise SystemExit(f"Creating a dashboard through MCP wasn't refused with 403: {text[:300]}")
    print("  ok: SigNoz refuses its writes (403)")

    reader = ["--as", "system:serviceaccount:lab6:ai-reader"]
    if kubectl(context, *reader, "-n", "lab3", "get", "pods").returncode != 0:
        raise SystemExit("The AI's Kubernetes account can't list pods.")
    if kubectl(context, *reader, "-n", "lab6", "get", "secrets").returncode == 0:
        raise SystemExit("The AI's Kubernetes account can read Secrets. It shouldn't.")
    print("  ok: its Kubernetes account can read pods, and not Secrets")

    print("Smoke test passed: Lab 6's MCP server and read-only access work.")


if __name__ == "__main__":
    main()
