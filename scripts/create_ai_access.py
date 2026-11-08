#!/usr/bin/env python3
"""Gives Lab 5's AI read-only access to SigNoz and Kubernetes.

1. A SigNoz service account, lab5-ai, with the signoz-viewer role. Its key goes
   into the Kubernetes Secret lab5/signoz-viewer, for the MCP server. SigNoz
   refuses any change made with it.
2. A kubeconfig for the lab5/ai-reader ServiceAccount, for agents on your
   machine: labs/lab5-ai/workspace/.kubeconfig. RBAC in
   labs/lab5-ai/k8s/reader-rbac.yaml makes it read-only.

Safe to rerun: an existing key is kept while SigNoz still accepts it.
Usage: create_ai_access.py KUBE_CONTEXT
"""

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

from signoz_client import SIGNOZ_URL, request, session

ACCOUNT = "lab5-ai"
ROLE = "signoz-viewer"
NAMESPACE = "lab5"
WORKSPACE = Path(__file__).resolve().parent.parent / "labs/lab5-ai/workspace"


def kubectl(context, *args, stdin=None):
    return subprocess.run(["kubectl", "--context", context, *args], input=stdin, capture_output=True, text=True, check=True).stdout


def current_key(context):
    """The key in the Secret, or None."""
    try:
        data = json.loads(kubectl(context, "-n", NAMESPACE, "get", "secret", "signoz-viewer", "-o", "json"))
    except subprocess.CalledProcessError:
        return None
    return base64.b64decode(data["data"]["api-key"]).decode()


def find_account(admin):
    status, body = request(f"{SIGNOZ_URL}/api/v1/service_accounts", token=admin)
    if status != 200:
        raise SystemExit(f"Could not list service accounts (HTTP {status}).")
    for account in body["data"]:
        # Deleted accounts stay in the list.
        if account.get("name") == ACCOUNT and account.get("status") != "deleted":
            return account["id"]
    return None


def create_account(admin):
    status, body = request(f"{SIGNOZ_URL}/api/v1/service_accounts", {"name": ACCOUNT}, admin)
    if status not in (200, 201):
        raise SystemExit(f"Could not create service account {ACCOUNT} (HTTP {status}).")
    account = body["data"]["id"]
    status, roles = request(f"{SIGNOZ_URL}/api/v1/roles", token=admin)
    role = next(r["id"] for r in roles["data"] if r["name"] == ROLE)
    status, _ = request(f"{SIGNOZ_URL}/api/v1/service_account_roles", {"serviceAccountId": account, "roleId": role}, admin)
    if status not in (200, 201):
        raise SystemExit(f"Could not give {ACCOUNT} the {ROLE} role (HTTP {status}).")
    print(f"Created service account {ACCOUNT} with role {ROLE}.")
    return account


def new_key(admin, account):
    # Old keys would keep working, so remove them first.
    status, keys = request(f"{SIGNOZ_URL}/api/v1/service_accounts/{account}/keys", token=admin)
    for key in (keys or {}).get("data") or []:
        request(f"{SIGNOZ_URL}/api/v1/service_accounts/{account}/keys/{key['id']}", token=admin, method="DELETE")
    status, body = request(f"{SIGNOZ_URL}/api/v1/service_accounts/{account}/keys", {"name": "mcp-server", "expiresAt": 0}, admin)
    if status not in (200, 201):
        raise SystemExit(f"Could not create a key for {ACCOUNT} (HTTP {status}).")
    return body["data"]["key"]


def store_key(context, key):
    # Through stdin, so the key never appears in a process list.
    secret = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": "signoz-viewer", "namespace": NAMESPACE},
        "stringData": {"api-key": key},
    }
    kubectl(context, "apply", "-f", "-", stdin=json.dumps(secret))


def write_kubeconfig(context):
    """A kubeconfig for ai-reader, with this cluster's address and CA."""
    full = json.loads(kubectl(context, "config", "view", "--raw", "--minify", "--flatten", "-o", "json"))
    cluster = full["clusters"][0]["cluster"]
    # Valid for 30 days. Rerun make lab5 for a new one. This calls the
    # TokenRequest API directly, because `kubectl create token` needs kubectl 1.24+.
    request_body = {"apiVersion": "authentication.k8s.io/v1", "kind": "TokenRequest", "spec": {"expirationSeconds": 30 * 24 * 3600}}
    response = kubectl(context, "create", "--raw", f"/api/v1/namespaces/{NAMESPACE}/serviceaccounts/ai-reader/token", "-f", "-", stdin=json.dumps(request_body))
    token = json.loads(response)["status"]["token"]
    config = {
        "apiVersion": "v1",
        "kind": "Config",
        "clusters": [{"name": "lab", "cluster": cluster}],
        "users": [{"name": "ai-reader", "user": {"token": token}}],
        "contexts": [{"name": "ai-reader", "context": {"cluster": "lab", "user": "ai-reader"}}],
        "current-context": "ai-reader",
    }
    path = WORKSPACE / ".kubeconfig"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as file:
        json.dump(config, file, indent=1)
    print(f"Wrote {path.relative_to(WORKSPACE.parent.parent.parent)}: read-only Kubernetes access for agents on this machine.")

    # Claude Code started in the workspace passes this to every command it runs,
    # so its kubectl uses the read-only account instead of your own login.
    # Machine-specific, so it's git-ignored.
    local = WORKSPACE / ".claude/settings.local.json"
    local.write_text(json.dumps({"env": {"KUBECONFIG": str(path)}}, indent=2) + "\n")
    print(f"Wrote {local.relative_to(WORKSPACE.parent.parent.parent)}: points the workspace's kubectl at it.")


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: create_ai_access.py KUBE_CONTEXT")
    context = sys.argv[1]
    admin = session()
    if not admin:
        raise SystemExit("No way to log in to SigNoz: .lab-credentials is missing.")

    account = find_account(admin) or create_account(admin)
    key = current_key(context)
    if key and request(f"{SIGNOZ_URL}/api/v2/rules", api_key=key)[0] == 200:
        print(f"Kept the existing key for {ACCOUNT}.")
    else:
        store_key(context, new_key(admin, account))
        print(f"Stored a new key for {ACCOUNT} in Secret {NAMESPACE}/signoz-viewer.")

    # Prove the key can read and can't write, rather than trust the role name.
    key = current_key(context)
    read = request(f"{SIGNOZ_URL}/api/v2/rules", api_key=key)[0]
    write = request(f"{SIGNOZ_URL}/api/v2/dashboards", {"title": "should be refused"}, api_key=key)[0]
    if read != 200 or write != 403:
        raise SystemExit(f"Expected read 200 and write 403 with the viewer key, got {read} and {write}.")
    print(f"Viewer key checked: reading rules gives {read}, creating a dashboard gives {write}.")

    write_kubeconfig(context)


if __name__ == "__main__":
    main()
