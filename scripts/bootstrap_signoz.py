#!/usr/bin/env python3
"""Waits for SigNoz and creates the first admin.

This step is required, not cosmetic: SigNoz's collector does not open its OTLP
ports until an organization exists, so every pod looks healthy while all
telemetry is refused. The generated login is saved to .lab-credentials.
"""

import secrets

from signoz_client import CREDENTIALS, SIGNOZ_URL, login, read_credentials, request, wait_for


def version():
    status, body = request(f"{SIGNOZ_URL}/api/v1/version")
    return body if status == 200 and body else None


def main():
    info = wait_for("SigNoz (first boot downloads several images)", version, timeout=1200)
    credentials = read_credentials()

    if info.get("setupCompleted"):
        if not credentials:
            print("SigNoz already has an admin, but .lab-credentials is missing.")
            print("Create that file as described in README.md, or the smoke test and tutorial cannot query SigNoz.")
        elif not login(credentials):
            raise SystemExit("The login in .lab-credentials was refused by SigNoz.")
        return

    if not credentials:
        credentials = {
            "SIGNOZ_URL": SIGNOZ_URL,
            "SIGNOZ_EMAIL": "admin@lab.local",
            "SIGNOZ_PASSWORD": f"Lab-{secrets.token_hex(8)}-Aa1!",
        }
        CREDENTIALS.touch(mode=0o600)
        CREDENTIALS.write_text("".join(f"{key}={value}\n" for key, value in credentials.items()))

    status, _ = request(
        f"{SIGNOZ_URL}/api/v1/register",
        {
            "name": "Lab Admin",
            "orgName": "signoz-lab",
            "email": credentials["SIGNOZ_EMAIL"],
            "password": credentials["SIGNOZ_PASSWORD"],
        },
    )
    if status != 200:
        raise SystemExit(f"Could not create the SigNoz admin (HTTP {status}).")
    print(f"Created SigNoz admin {credentials['SIGNOZ_EMAIL']}. Login saved to .lab-credentials.")


if __name__ == "__main__":
    main()
