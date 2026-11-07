# Telemetry tutorial

An interactive tutorial on OpenTelemetry and SigNoz, using this repo's lab as the worked example.

## Start it

From the repo root:

```bash
make tutorial
```

Then open http://127.0.0.1:8765. Press Ctrl+C to stop.

It needs Python 3 and nothing else: no packages, no build step. Use the server rather than opening
the HTML files directly, because the pages load their saved examples through it.

## What is inside

| Page | Covers |
|---|---|
| `concepts.html` | Traces, metrics and logs, and how they connect here |
| `lab1.html` | Lab 1: telemetry with no code, using the OpenTelemetry Operator |
| `incident-error.html`, `-latency`, `-cross-service`, `-slow-sql`, `-timeout`, `-cpu` | Lab 1: six incidents, solved with no code |
| `instrumentation.html` | Lab 2: the whole difference from Lab 1, quoted with file and line numbers |
| `incident-slow-item.html`, `-free-orders`, `-cache-miss`, `-trace-id` | Lab 2: four incidents, each shown in both labs |
| `lab3.html` | Lab 3: what Kubernetes tells you, and the extra scrape jobs |
| `incident-throttling.html`, `-oom`, `-liveness`, `-node`, `-apiserver` | Lab 3: five failures at the pod, node and API server level |
| `lab4.html` | Lab 4: alert rules, each proved against a real failure |
| `queries.html` | Working searches for traces, logs and metrics, labelled by lab, plus ClickHouse SQL |
| `gaps.html` | What a plain install leaves out, and possible fixes |

## How the live parts work

The app sends no CORS headers and SigNoz needs a login, so `server.py` sits between the pages and
the lab. The bridge is narrow:

- It runs the known scenarios on any lab, controls each lab's load generator, and reads the alerts
  Lab 4 received.
- It runs read-only searches: the saved catalogue in `data/queries.json`, a lookup of one trace by
  ID, and a fixed search for the trace of a scenario it has just fired.
- It reads `.lab-credentials` when it starts a session. The password stays in the server and is
  never sent to the browser.
- It listens on `127.0.0.1` only, and refuses requests from other origins.

Lab 1's API returns no trace ID, so after firing a Lab 1 scenario the page asks the bridge to find
it in SigNoz. The bridge sends scenarios with the `User-Agent` `telemetry-tutorial` and searches for
that, so it finds its own request even while the load generator is hitting the same route. A trace
usually takes a few seconds to arrive, and the page shows a waiting state until it does.

It does not change SigNoz or the app. Scenarios and load do create telemetry, so stop the load
generator when you finish.

## If the lab is down

The pages still work. Each lab is checked on its own, so Lab 1 keeps working when Lab 2 is not
deployed, which is normal after `make up`. A banner reports both labs, live buttons for anything
down turn off, and every walkthrough shows its saved example from a real run.

## Saved data

| Folder | Contents |
|---|---|
| `data/evidence.json` | Spans and logs from the saved scenario runs, keyed by lab |
| `data/queries.json` | The query catalogue, with real saved results and how each was checked |
| `data/clickhouse.json` | ClickHouse SQL and its real output |
| `screenshots/` | Real SigNoz screenshots from this lab |

All of it was captured on 2026-11-07 (UTC), on the labs as they are now. SigNoz keeps traces and
logs for 15 days, so links to saved trace IDs stop working after about 2026-11-22. The saved copies
stay.

Optional settings: `TUTORIAL_PORT`, `TUTORIAL_LAB1_URL`, `TUTORIAL_LAB2_URL`, `TUTORIAL_SIGNOZ_URL`.
