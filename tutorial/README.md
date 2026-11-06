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
| `instrumentation.html` | Lab 2: the real setup code, quoted with file and line numbers |
| `incident-*.html` | Lab 2: six walkthroughs: error, latency, cross-service, slow SQL, timeout, CPU |
| `queries.html` | Working searches for traces, logs and metrics, plus ClickHouse SQL |
| `gaps.html` | What a plain install leaves out, and possible fixes |

## How the live parts work

The app sends no CORS headers and SigNoz needs a login, so `server.py` sits between the pages and
the lab. The bridge is narrow:

- It runs the known scenarios and controls the load generator.
- It runs read-only searches: the saved catalogue in `data/queries.json`, and a lookup of one
  trace by ID.
- It reads `.lab-credentials` when it starts a session. The password stays in the server and is
  never sent to the browser.
- It listens on `127.0.0.1` only, and refuses requests from other origins.

It does not change SigNoz or the app. Scenarios and load do create telemetry, so stop the load
generator when you finish.

## If the lab is down

The pages still work. Live buttons turn off, a banner says so, and every walkthrough shows its
saved example from a real run.

## Saved data

| Folder | Contents |
|---|---|
| `data/evidence.json` | Spans and logs from the saved scenario runs |
| `data/queries.json` | The query catalogue, with real saved results and how each was checked |
| `data/clickhouse.json` | ClickHouse SQL and its real output |
| `data/overview.json` | Services, Service Map and Exceptions API captures |
| `screenshots/` | Real SigNoz screenshots from this lab |

All of it was captured on 2026-11-04 and 2026-11-05 (UTC). SigNoz keeps traces and logs for 15
days, so links to saved trace IDs stop working after about 2026-11-19. The saved copies stay.

Optional settings: `TUTORIAL_PORT`, `TUTORIAL_APP_URL`, `TUTORIAL_SIGNOZ_URL`.
