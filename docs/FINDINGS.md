# SigNoz evaluation: what a dev gets from plain OpenTelemetry + a simple install

Most of these findings were measured on an earlier hand-instrumented version of the app, in the
namespace `lab`. The section "Hands-off versus custom dimensions" covers today's two labs.

Tested 2026-11-04 with SigNoz chart 0.149.0, k8s-infra chart 0.17.1, ClickHouse 25.12.5,
k3s v1.26.4 on k3d, OTel Python SDK 1.45.2 (instrumentation 0.66b2), Python 3.13.

## Bottom line

The data side is strong. With only standard OTel code and env vars, SigNoz stored cross-service
traces, SQL text, exceptions, trace-linked logs and custom metrics, with no SigNoz-specific code.

The overview side had a serious gap in this lab: **`backend` only appears on the Services page
when a rare match falls inside your time range, and the Service Map shows about 1% of its real
calls from `frontend`**, although both services are fully traced. One app setting fixed
the listing, but map counts stay unreliable, especially with two collectors (gap 2). A new install also has **no dashboards and no alerts**, and it **rejects all
telemetry until someone signs up**.

Plan to configure six things yourself: signup, a shorter span flush interval, Kubernetes context,
log deduplication, dashboards and alerts. Details and fixes are below.

## How each claim was checked

| Label | Meaning |
|---|---|
| **UI** | Seen on the SigNoz page itself |
| **API** | Returned by the API the UI uses |
| **Data** | Confirmed in ClickHouse, but the UI page was not viewed |
| **Untested** | A proposal. Not applied in this lab |

The test machine was under heavy load from unrelated work, so browser automation kept timing out
during the evaluation. More pages
were captured later while building the tutorial, in `tutorial/screenshots/`.
The cluster itself was healthy: about 10% CPU, API responses around 15 ms. Any slowness seen in
the UI here says nothing about SigNoz.

## What works with no configuration

| Capability | Result | Checked |
|---|---|---|
| Services page for `frontend`: P99, error rate, ops/s | Works, generated from spans | UI |
| Traces across services (`frontend → backend → SQL`) | One trace, correct parent/child links | UI |
| SQL text on spans, including the failing statement | Present (`db.statement`) | UI |
| Exceptions recorded with type | `ZeroDivisionError`, `psycopg.errors.UndefinedTable`, `RuntimeError`, `httpx.ReadTimeout` | UI |
| Logs linked to traces (OTLP logs) | App logs written during a request carry its trace ID | UI |
| Custom metrics (`orders.created`, `scenario.runs`, ...) | Stored | Data |
| HTTP metrics from instrumentation | `http.server.duration`, `http.client.duration`, ... | Data |
| APM metrics without any app metrics | Collector derives `signoz_calls_total`, `signoz_latency` from spans | Data |
| Database in the Service Map | `backend → postgresql` edge present | UI |
| Retention defaults | Traces 15 days, logs 15 days, metrics 30 days | API |

Useful detail from the `timeout` scenario: the trace shows the frontend giving up at 1008 ms
while the backend kept working until 3002 ms. That kind of wasted work is hard to see in logs.

## Gaps, most important first

### 1. Fresh install rejects telemetry until first signup

- **What happens:** the collector pod is Ready and logs `Everything is ready`, but ports 4317 and
  4318 are closed. Apps get `Connection refused`, and that telemetry is lost.
- **Why:** the server logs `cannot create agent without orgId`. Until an organization exists, the
  collector never receives its real config over OpAMP.
- **Proof:** creating the first admin opened both ports within seconds and stopped the errors.
- **Do this:** complete signup right after install, and include it in any automated setup.
  `kubectl get pods` will not warn you.

### 2. `backend` comes and goes on Services, and the Service Map undercounts it

**Status: improved, not fixed.** `OTEL_BSP_SCHEDULE_DELAY=500` helps a lot, but the result depends on
whether a parent and child reach the same collector. Calls that all crossed nodes gave about 44%
with spans on one collector. In one later run, `lab1-backend` was missing from Services, and the map
showed 0 of 3,216 calls. That run could not be reproduced. Which collector an agent uses is decided
by chance when it connects, so the outcome can change between restarts. Results are at the end of
this section. Everything before them describes the default 5-second flush.

- **Services:** whether `backend` is listed depends on your time range. On 2026-11-05 a range
  starting at 01:50 UTC listed it, and one starting at 01:56 did not (**API**). For about the first
  40 minutes it was not listed at all (**UI**, `docs/screenshots/01-services.png`).
- **Service Map:** the `frontend → backend` link is missing from some ranges. Where it appears, it
  showed 262 calls against about 22,800 real ones, roughly 1% (**API**), so don't trust that count.
  The `backend → postgresql` link is not affected.
- **Service page:** `/services/backend` opens by direct URL. In a range with no match, its
  Entrypoint Spans table is empty, while Key Operations still shows real data.
- **Not a data problem:** backend's spans are all stored, and running the same join by hand finds
  all its operations.
- **Cause (confirmed):** both features depend on ClickHouse materialized views that self-join
  spans: `sub_root_operations` and `dependency_graph_minutes_service_calls_mv_v2`. Those views only
  match a parent and child that arrive **in the same insert**. Each service flushes on its own
  5-second timer, so they usually land in different inserts.
- **Evidence:** in the first test the views ran 322 and 352 times with no errors and wrote 0 rows.
  They read exactly 2× the inserted rows, so they never read stored data. An isolated reproduction
  agrees:

  | Parent and child inserted | Analyzer | Row written? |
  |---|---|---|
  | Separately | on | No |
  | Together | on | Yes |
  | Separately | off | No |

  The analyzer is therefore not the likely cause, although the `off` setting may not have reached
  the view, so that row is not conclusive.
- **Rare matches do happen:** by 02:04 UTC, 19 of 1,931 view runs had written rows, around 23:10
  and 01:55 UTC, with no config change. That fits the explanation above, since timers can line up
  briefly, but those specific inserts were not inspected.
- **Listing rule:** a service appears when its `top_level_operations` row has a `time` at or after
  the start of your range. This comes from API tests, not from reading SigNoz's source.
- **Unknown:** why the timing lined up when it did, and how often this hits real deployments.
  A few searches of SigNoz's issue tracker found nothing, which is weak evidence.
- **Fix applied:** `OTEL_BSP_SCHEDULE_DELAY=500` on both services, so spans flush inside the
  collector's 1-second batch window. Measured over 5 minutes at 5 requests/s with 10% errors:

  | | 5-second flush (default) | 500 ms flush |
  |---|---|---|
  | View runs that wrote rows | 19 of 1,931 (1%) | 302 of 302 (100%) |
  | `frontend → backend` calls on the map, against real calls | 262 of about 22,800 (1%) | 1,207 of 1,415 (85%) |
  | `backend` listed in a last-60-seconds range | Rarely | 10 of 10 checks |
  | Export errors | 0 | 0 |

- **Limits of that test:**
  - It was short, on one node, with one collector replica and almost no network delay.
  - Map counts were still about 15% low, most likely from pairs split across two batches.
  - **It does not hold with two collectors:** accuracy fell to 41%. See "Two nodes and HA".
  - Exports can be up to 10× more frequent. The cost of that was not measured.
- **Other options (Untested):**
  - Add a `loadbalancing` exporter keyed on trace ID, so a whole trace reaches one collector.
    This is the next thing to try with two collectors.
  - Add a `groupbytrace` processor in a collector before SigNoz, so a trace's spans are sent
    together.
  - Report it upstream with the reproduction above.

### 3. App telemetry has no Kubernetes context, even after k8s-infra

**Status: fixed** by sending app telemetry through the agent, tested 2026-11-05.

- **What happened:** 0 of about 8,500 recent spans had `k8s.pod.name` (**Data**). You could not go
  from a slow trace to the pod that served it.
- **Why:** the app sent straight to SigNoz's collector, skipping the agent that adds these
  attributes.
- **Fix applied:** point the app at the agent, which has `k8sattributes` on all three pipelines:
  `OTEL_EXPORTER_OTLP_ENDPOINT=http://k8s-infra-otel-agent.signoz.svc.cluster.local:4318`
- **Result:** all 5,767 spans in a test window had pod and node names, and they matched `kubectl`.
  OTLP logs and custom metrics got them too (**Data**).
- **On several nodes:** each agent only knows its own node's pods. The chart's Service uses
  `internalTrafficPolicy: Local` to keep traffic on the node, so a node with no agent loses its
  apps' telemetry. Check tolerations.

### 4. k8s-infra duplicates every app log, and the copies are incomplete

| | OTLP copy | stdout copy (k8s-infra) |
|---|---|---|
| `service.name` | Yes | Blank |
| Kubernetes attributes | Yes, since the gap 3 fix | Yes |
| Severity | Yes | Blank |
| Link to trace | Yes | No |
| Count, 5-minute sample (frontend / backend) | 3,017 / 1,015 | 5,597 / 3,274 |

- **Effect:** more storage, and searches return mixed results that filter differently (**Data**).
- **Worse than a plain copy:** of about 166,000 stdout records, roughly 46% are stack-trace
  fragments, because each line of a traceback becomes its own record. About 29% are app lines and
  24% are access-log lines (**Data**, classified by pattern, so approximate).
- **Fix (Untested):** keep OTLP logs, which now go through the agent (gap 3), and exclude the lab
  namespaces from `filelog` collection. Alternatively drop OTLP logs, print JSON to stdout and parse
  it with a SigNoz log pipeline.

### 5. Nothing is set up for you: dashboards, alerts, pipelines

A fresh install has 0 dashboards, 0 alert rules, 0 notification channels, 0 log pipelines and
0 saved views (**API**).

- **Dashboards:** [SigNoz/dashboards](https://github.com/SigNoz/dashboards) has 121 folders and was
  updated 2026-10-23. Most relevant here: `apm/` (APM, DB calls, HTTP API), `k8s-infra-metrics/`
  (cluster, nodes, pods, PVCs, events), `postgresql/`, `hostmetrics/`, `opentelemetry-collector/`,
  `signoz-ingestion-analysis/`. None were imported, so whether they suit this data is **Untested**.
- **Built-in integrations:** 8 are available, none installed: PostgreSQL, Redis, Mongo, Nginx,
  ClickHouse and 3 AWS ones.
- **Alerts:** that repo contains no alert definitions. I did not find a ready-made alert pack, but
  that search was limited. Expect to write your own rules.

### 6. Smaller issues

- **Span noise:** more than half of stored spans (47,450 of 84,695) are zero-length ASGI `http send` and
  `http receive` spans. `FastAPIInstrumentor.instrument_app` has an `exclude_spans` argument that
  should remove them, but it is a code argument, and the injected agent has no setting for it
  (**Untested**).
- **Vague span names:** client spans are named just `GET` or `POST`, and every scenario shares the
  operation `POST /api/scenario/{name}`. The custom `lab.scenario` attribute separates them.
- **4xx is not an error:** `bad_input` has span status Unset, which follows OTel conventions. It
  will not raise the error rate, so alert on 4xx separately if you care.
- **SDK exporter logs ship as app logs:** the OTel exporter's own failures reached SigNoz as
  `WARN`/`ERROR` logs through the root logger. These were the only app logs with no trace ID.
- **Older attribute names:** the instrumentation emits `http.server.duration`, `db.statement` and
  `net.peer.name`, not the newest conventions. Check this when importing dashboards.
- **Silent misconfiguration:** a k8s-infra endpoint without `http://` installs fine and pods stay
  Running, while every export fails. Check collector logs, not pod status.
- **Outbound call:** the self-hosted UI requests release notes from `cms.signoz.cloud`.

## k8s-infra: before and after

| | App + SigNoz only | Plus k8s-infra |
|---|---|---|
| Pod, node, container, volume metrics | None | Yes: 19 pod metrics, 22 node metrics, and more |
| Kubernetes events | None | Yes (`Scheduled`, `Killing`, ...) |
| Container stdout logs | None | Yes, including Postgres |
| CPU spike visible | No | Yes: `cpu_burn` took `k8s.pod.cpu.usage` from 0.03 to 0.8 cores |
| Kubernetes attributes on app traces | No | Yes, once apps send through the agent (gap 3) |
| Duplicate app logs | No | Yes (gap 4) |
| Infra Monitoring UI | Not checked | Hosts tab works (**UI**). Kubernetes tab **not verified:** its data never finished loading |

## Hands-off versus custom dimensions

Tested 2026-11-07 with `make compare`, which sends both labs the same requests. Both use the same
injected agent. Lab 1's app has no OpenTelemetry code. Lab 2 adds a few API calls, with no SDK setup.

| What SigNoz received | Lab 1 | Lab 2 |
|---|---|---|
| Traces crossing both services | Yes | Yes |
| SQL text on spans | Yes | Yes |
| Spans marked as errors | Yes | Yes |
| Pod names on spans | Yes | Yes |
| Logs linked to traces | Yes | Yes |
| HTTP and Python runtime metrics | Yes | Yes |
| Log fields from plain `logging` (`order.item`) | Yes | Yes |
| Custom span (`price_order`) | No | **Yes** |
| Business attribute on spans (`order.item`) | No | **Yes** |
| Technical attribute on spans (`cache.hit`) | No | **Yes** |
| Scenario name on spans (`lab.scenario`) | No | **Yes** |
| Business metric (`orders.created`) | No | **Yes** |
| Trace ID in the API response | No | **Yes** |

- **You don't have to choose.** Code using only the OpenTelemetry API works on top of the injected
  agent, so you can keep hands-off instrumentation and add detail only where you need it.
- **All six debugging incidents are solvable with no code.** Exceptions, SQL text, slow spans and pod
  CPU are enough to find each root cause.
- **Logs are the first free dimension.** Python logs need one setting. After that, plain `logging`
  `extra=` fields become searchable, linked to traces, and can be counted, summed and charted.
- **Log fields have limits.** They can't be connected to latency, because the field is on the log and
  the duration is on the span. And you can't see a field nobody logged.
- **The agent turns on everything that applies,** including process, runtime and system metrics, so
  expect more metric series than you'd choose yourself.
- **Injection can fail silently.** The Operator's webhook fails open, so if it can't answer, pods
  start healthy with no agent and no error. This happened here: by default, each `helm upgrade`
  makes a new webhook certificate, and pods created in the roughly 16 seconds before the Operator
  loaded it got no telemetry. Set `autoGenerateCert.recreate: false`, and check pods were injected.

### Metric labels and cardinality

The same 1,000 orders were sent as two metrics, with different labels:

| Label | Distinct values | Series | Samples stored |
|---|---|---|---|
| `order.item` | 5 | 5 | 65 |
| `order.id` | 1,000 | 1,000 | 13,000 |

Put unbounded values on spans or logs, not on metric labels.

**Recommendation:** start hands-off, use log fields where they're enough, and add span attributes and
metrics where you need to connect a value to latency or track it over time.

eBPF instrumentation (OBI) and Odigos were not tested.

## Two nodes and HA

Tested 2026-11-05. Two nodes, two replicas of `frontend` and `backend` (one per node), telemetry
through the node agents, two SigNoz collectors (one per node). All of this is real but runs inside
one Docker VM, so it shows Kubernetes behaviour, not real hardware failure.

### Node crash test

The worker node was crashed with `docker kill` under 5 requests/s from outside, and restarted after
150 seconds.

| Period | Requests | Result |
|---|---|---|
| First 45 seconds | About half failed (109 of 220) | Requests sent to dead pods hung until the 8-second client timeout |
| 45 seconds until the node returned | 0 failed | One node carried everything, P95 about 55 ms |
| Node rejoining | 0 failed | Ready again 7 seconds after restart |

- **Why 45 seconds:** Kubernetes removed the dead pods from the Service at about 44 seconds. That
  delay comes from node failure detection, so plan for it. Client retries or shorter timeouts would
  reduce the impact (**Untested**).
- **Telemetry survived:** 1,086 of 1,090 successful requests kept their trace (99.6%), and 1,071
  had spans from both services. Most incomplete traces came as the node rejoined.
- **Not tested:** rescheduling. The node returned before Kubernetes' default 5-minute eviction, so
  replacement pods never started.

### What is still a single point of failure

Losing the worker is survivable. **Losing `server-0` would stop the app and SigNoz** (not tested,
but it follows from placement). These all run there, once:

- k3s control plane
- ClickHouse and ZooKeeper
- SigNoz server and UI
- Postgres
- Traefik, and the k3d load balancer only forwards to that node

The `local-path` volumes also tie ClickHouse, ZooKeeper, and SigNoz's own data to that node. Real
HA for these needs replicated databases, network storage and three control-plane nodes.

### Service Map accuracy by setup

Same load each time. All setups listed `backend` in every last-60-seconds check.

| Setup | Map calls vs real | Accuracy |
|---|---|---|
| 1 node, 1 replica each, direct to collector | 1,207 of 1,415 | 85% |
| 2 nodes, 2 replicas, direct to collector | 608 of 853 | 71% |
| 2 nodes, through agents, 1 collector | 718 of 854 | 84% |
| 2 collectors, but all spans happened to use one | 509 of 865 | 59% |
| 2 collectors, spans really split | 358 of 871 | 41% |

- **Agents help:** they merge senders into fewer streams.
- **Two collectors hurt:** a parent and child on different collectors can never share an insert.
  The 41% run counted fewer calls than its 494 same-node calls.
- **The 59% run is not a two-collector result.** Spans used one collector, as in the 84% run, but
  59% of calls crossed nodes instead of 31%. Crossing nodes seems to cost accuracy, but two runs
  are too few to prove it.
- **Likely fix (Untested):** a `loadbalancing` exporter in the agents, keyed on trace ID, sends a
  whole trace to one collector. This is the standard OTel pattern for this kind of problem.

### Traps found

- **`ScheduleAnyway` is not HA.** The scheduler put every replica on the emptier node. Pods were
  healthy, and one failure would have stopped the app. The SigNoz chart's collector default is also
  `ScheduleAnyway`, although the two collectors did land on separate nodes here.
- **`DoNotSchedule` alone is not enough.** A rollout left every replica on one node again, because
  the rule is only checked at scheduling and counts old pods. `maxSurge: 0` fixed it, confirmed over
  two rollouts. On Kubernetes 1.27+, `matchLabelKeys` is the cleaner fix.
- **Two collectors do not balance themselves.** Each agent holds a connection per signal, so one
  collector can take every span while the other handles only logs and metrics. Which one is decided
  by chance when the agent connects.
- **Restarting an agent leaves a gap.** The agent Service's `Local` policy has no fallback, so
  apps on that node failed 4 metric exports during one restart.
- **In-process state breaks with replicas.** The load generator had to become its own Deployment.

## Resource use

The SigNoz namespace used about 3.8 GiB (ClickHouse 2.7 GiB, ZooKeeper 0.8 GiB) and the k3d node
about 5.3 GiB in total, after about 30 minutes at 5 requests/s. That is a small dataset (about
10 MiB on disk), so treat these as a starting point, not a sizing guide.

## Not caused by SigNoz

**k3d needs a mount fix** for the agent. kind and real Kubernetes nodes do not.

## Next steps

Suggested order. Nothing here has been applied.

1. Remove the noisy ASGI spans. This saves more than half of stored spans and loses nothing.
2. Try trace-ID load balancing, to restore map accuracy with two collectors.
3. Add `memory_limiter`, and send the collectors' own metrics to SigNoz.
4. Remove duplicate logs (gap 4).
5. Import dashboards from `apm/`, `k8s-infra-metrics/` and `postgresql/`.
6. Write alerts, for example error rate, P99 latency and pod CPU, plus a notification channel.
7. Decide how far HA should go: ClickHouse, ZooKeeper, Postgres and the control plane.

`BENCHMARK.md` explains this order, and why sampling is not on the list yet.
