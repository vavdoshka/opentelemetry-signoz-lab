# SigNoz telemetry lab

[![e2e](https://github.com/vavdoshka/signoz-poc/actions/workflows/e2e.yml/badge.svg)](https://github.com/vavdoshka/signoz-poc/actions/workflows/e2e.yml)

What do you get from plain OpenTelemetry and a simple SigNoz install on Kubernetes, and what's
missing? This lab lets you find out hands-on.

`make up` starts a local two-node cluster with SigNoz and a small instrumented app that can fail on
demand. An interactive tutorial then walks you through finding and fixing each failure.

## Prerequisites

| Tool | macOS | Linux |
|---|---|---|
| Docker | [Docker Desktop](https://docs.docker.com/desktop/setup/install/mac-install/) | [Docker Engine](https://docs.docker.com/engine/install/) |
| k3d (or kind) | `brew install k3d` | [Install k3d](https://k3d.io/#installation) |
| kubectl | `brew install kubectl` | [Install kubectl](https://kubernetes.io/docs/tasks/tools/) |
| Helm | `brew install helm` | [Install Helm](https://helm.sh/docs/intro/install/) |
| Python 3.9 or newer | `brew install python` | Usually already installed |
| make | `xcode-select --install` | `sudo apt install make` |

You also need:

- **Memory:** at least 8 GB for Docker, and 10 GB is better. On Docker Desktop, set this in
  Settings > Resources.
- **Port 8080** free on your machine.

Run `make check` to confirm everything is ready. It tells you how to fix anything that isn't. On
some Linux machines it will ask you to add one line to `/etc/hosts`.

## Quick start

```bash
git clone https://github.com/vavdoshka/signoz-poc.git
cd signoz-poc
make up
```

The first run downloads several images, so allow about 5 to 10 minutes. It finishes with a smoke test
that proves traces, logs and metrics are reaching SigNoz.

| What | Where |
|---|---|
| Test app | http://app.localhost:8080 |
| SigNoz | http://signoz.localhost:8080 (the generated login is in `.lab-credentials`) |
| Tutorial | Run `make tutorial`, then open http://127.0.0.1:8765 |

Start the load generator in the test app, so SigNoz has data to show.

## Commands

| Command | What it does |
|---|---|
| `make check` | Checks the prerequisites |
| `make up` | Creates the cluster and deploys everything. Safe to rerun, and recovers the lab after a restart |
| `make status` | Shows nodes, pods and URLs |
| `make app` | Rebuilds and redeploys the test app after you change its code |
| `make tutorial` | Runs the interactive tutorial |
| `make down` | Deletes the cluster and all its data |

k3d is the default. To use kind, run `make up PROVIDER=kind`. The other commands find the running
cluster themselves.

## The test app

`frontend → backend → Postgres`: two Python FastAPI services with two replicas each, one per node.
They use only standard OpenTelemetry libraries, and send traces, metrics and logs through the
SigNoz agent on their node. The UI has a button for each scenario:

| Scenario | What it does |
|---|---|
| `order`, `list` | Normal requests through to Postgres |
| `slow` | Backend sleeps 1–3 s |
| `slow_query` | `SELECT pg_sleep(2)` |
| `timeout` | Backend takes 3 s, frontend gives up after 1 s (504) |
| `bad_input` | Handled 400 with a warning log |
| `crash` | Unhandled exception in the frontend (500) |
| `backend_500` | Unhandled exception in the backend, frontend returns 502 |
| `db_error` | Query on a missing table |
| `cpu_burn` | Burns CPU for N seconds, visible in pod metrics |
| `log_burst` | N log lines at a chosen level |

## What we found

- **[Findings](docs/FINDINGS.md):** what works with no configuration, what doesn't, and a node crash
  test.
- **[Benchmark](docs/BENCHMARK.md):** the lab scored against OpenTelemetry and SigNoz guidance.
- **[Configuration log](docs/CONFIG.md):** every non-default setting, and why.

## Tested on

| Platform | Provider | Result |
|---|---|---|
| macOS, Apple Silicon | k3d 5.5.0 | Clean boot passes |

Linux results come from the e2e workflow above.

## Troubleshooting

**Something broke after a restart.** Run `make up`. It restarts the cluster and reapplies what a
restart loses. Test orders are lost, because Postgres has no persistent volume, but SigNoz keeps its
data.

**You created the SigNoz admin yourself.** The smoke test and tutorial need that login. Save it in
`.lab-credentials`:

```
SIGNOZ_EMAIL=you@example.com
SIGNOZ_PASSWORD=your-password
```

**Pods fail with "too many open files" on Linux.** Raise the inotify limit:
`sudo sysctl fs.inotify.max_user_instances=1024`.

## Limits

This is a lab, not a production setup. It runs on one machine, and ClickHouse, ZooKeeper, Postgres
and the control plane each run as a single instance. The findings cover what production would need.

## Licence

[MIT](LICENSE). SigNoz is a separate project with its own licence. This repo installs it from
SigNoz's official Helm charts and doesn't include it.
