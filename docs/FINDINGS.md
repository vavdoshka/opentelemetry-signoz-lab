# SigNoz evaluation: what a dev gets from plain OpenTelemetry + a simple install

Most of these findings were measured on an earlier hand-instrumented version of the app, in the
namespace `lab`. "Hands-off versus custom dimensions" covers today's Labs 1 and 2, and "Kubernetes
coverage" and "Alerts" cover Labs 3 and 4.

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
  collector's default 1-second batch window. Measured over 5 minutes at 5 requests/s with 10% errors:

  | | 5-second flush (default) | 500 ms flush |
  |---|---|---|
  | View runs that wrote rows | 19 of 1,931 (1%) | 302 of 302 (100%) |
  | `frontend → backend` calls on the map, against real calls | 262 of about 22,800 (1%) | 1,207 of 1,415 (85%) |
  | `backend` listed in a last-60-seconds range | Rarely | 10 of 10 checks |
  | Export errors | 0 | 0 |

- **Limits of that test:**
  - It was short, on one node, with one collector replica and almost no network delay.
  - Map counts were still about 15% low, most likely from pairs split across two batches.
  - **It does not hold with two collectors:** accuracy fell to 41%. See "Two nodes and HA". A
    5-second collector batch later reached 74% in one run. See "Resource use".
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
  `signoz-ingestion-analysis/`. Lab 3 imports four Kubernetes ones. The others are **Untested** here.
- **Built-in integrations:** 8 are available, none installed: PostgreSQL, Redis, Mongo, Nginx,
  ClickHouse and 3 AWS ones.
- **Alerts:** that repo contains no alert definitions. I did not find a ready-made alert pack, but
  that search was limited. Expect to write your own rules, as Lab 4 does.

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

## Kubernetes coverage

Checked in this lab on 2026-11-07, on k3s 1.26.4, by causing each failure in Lab 3:

| Signal | With `k8s-infra` defaults | With Lab 3's scrape jobs |
|---|---|---|
| Pod CPU and memory | `k8s.pod.cpu.usage`, `k8s.pod.memory.working_set` | |
| Usage against limits | `k8s.container.cpu_limit_utilization`, `k8s.container.memory_limit_utilization` | |
| Restarts, and why | `k8s.container.restarts` by `k8s.container.status.last_terminated_reason` | |
| Why a pod was killed | Kubernetes events, stored as logs | |
| Node CPU, memory and disk | `k8s.node.*` | |
| Node conditions | `k8s.node.condition_ready`, and memory, disk and PID pressure | |
| CPU throttling | **No** | `container_cpu_cfs_throttled_periods_total` |
| Probe results | Only as events | `prober_probe_total` |
| The kubelet's own health | **No** | `kubelet_*` |
| The API server | **No** | `apiserver_*` |
| containerd and node services | **No** | **No.** k3d nodes have no systemd. `kubelet_runtime_operations_errors_total` is the closest signal |

On k3d, `system.*` metrics describe the Docker VM both nodes share, so they aren't truly per node.

### What each failure really showed

**Average CPU hides throttling.** At 2 requests/s, `k8s.container.cpu_limit_utilization` read about
0.23 while 19 to 32% of CPU periods were throttled. A 200m limit allows 20 ms per 100 ms period, and
one request needs about that much.

**Throttling can get a healthy pod killed.** The same burn gave two outcomes:

| Load | P50 before | P50 during | Slowest | Outcome |
|---|---|---|---|---|
| 2 requests/s | About 45 ms | About 330 ms | 1 s | Survived, no restart |
| 5 requests/s | About 40 ms | 12.2 s | 18.8 s | Killed by liveness after 24 seconds |

At 5 requests/s a queue built up and `/healthz` passed its 3-second timeout. Kubernetes recorded the
exit as `Completed`, so only the events show why.

**Most signals missed a real OOM kill:**

| Signal | Showed |
|---|---|
| `container_oom_events_total` | 0, in SigNoz and straight from cAdvisor |
| `k8s.container.status.reason` | 0 for `OOMKilled`. It's the current state, and the container was running again |
| Kubernetes events | A generic `BackOff`, with no mention of memory |
| `k8s.container.memory_limit_utilization` | Peaked at 0.863 |
| `k8s.pod.memory.working_set` | Climbed to 224 MiB: an early warning, not proof |
| `k8s.container.restarts` by `last_terminated_reason` | **`OOMKilled`**, the one that works |
| The kernel log, collected by Lab 3 | **The process, its memory and its container ID** |

The likely reason for the first is that the counter belongs to the cgroup the kill destroys. The app's
last log arrived 2 seconds before the kill, and it reported nothing else. The caller did: the load
generator recorded 38 failed calls.

**The kernel log has the most detail.** Its record of a kill names the process and shows it at 254 MiB of its
256 MiB limit. Its `cpuset` is the container ID, and it matched exactly the one Kubernetes reported:
`d27ba4de75b6…`. The collector can't read the kernel log itself, because the `journald` receiver needs
`journalctl` and the image has none, so Lab 3 runs a small privileged DaemonSet that reads `/dev/kmsg`.
On k3d both nodes share a kernel, so each line arrives twice.

**`k8s.container.memory_limit_utilization` misleads both ways.** It counts page cache and is sampled
every 30 seconds:

| Moment | Share of limit | Working set | RSS | In danger? |
|---|---|---|---|---|
| Just before the OOM kill | 0.863 | 224 MiB | 215 MiB | Yes |
| Writing a file in the `disk` scenario | 0.995 | 61 MiB | 51 MiB | No |

The lab's dashboard therefore charts working set.

**A failure counter can read 0 during a failure.** `prober_probe_total{result="failed"}` doesn't exist
until the first failure, so it first appears at 3. With no earlier value, `rate` and `increase` read 0
while `latest` reads 3. The alert uses the Kubernetes event instead.

**`apiserver_request_total` doesn't count requests refused at authorization.** 549 requests got a
403, and no `code="403"` series existed, in SigNoz or straight from the API server. Client spans
(`response_status_code = '403'`) found all 549. That's measured on k3s 1.26.4, and newer versions are
**Untested**.

**The API server's metrics can't say who's calling, and its audit log can.** `apiserver_request_total`
has no client or user label. With the audit log on, a 2-minute `api_flood` showed 2,014 `list pods` from
`system:serviceaccount:lab3:workload`, exactly the app's own count, and no other caller above 3. An app's
own client spans show the same, but only for apps you instrument.

**Refused requests: the metric had none, the audit log had all of them.** In a second `api_denied` run the
app counted 1,975 403s. `apiserver_request_total` again had no 403 series, and the audit log recorded
1,975, all from the workload's ServiceAccount.

**Span counts can run high.** The client spans for that run said 2,039. At 00:48:20 SigNoz's collector
timed out writing a batch to ClickHouse (`context deadline exceeded`) and retried the whole batch, so 64
spans were stored twice, all from that batch, each with the same span ID as its twin.
`count_distinct(span_id)` gave 1,975. Delivery is at least once.

**Disk shows on the node, not the pod.** Writing 512 MiB to an `emptyDir` raised
`k8s.node.filesystem.usage` by about 467 MiB, on both nodes, because k3d nodes share a disk.
`k8s.pod.filesystem.usage` didn't move.

### Logs from the cluster and the node

| Log | Collected by default? | In Lab 3 |
|---|---|---|
| `kube-system` pods | No: the chart excludes the namespace | Yes. About 2 lines a minute here |
| Kernel log | No | Yes, through a DaemonSet |
| kubelet, API server and scheduler on k3s | No: they go to k3s's output, which k3d sends to `docker logs` | Yes. k3s's `--log` flag, set when the cluster is created, also writes `/var/log/k3s.log`, and the agents read it |
| kubelet on kubeadm clusters | No: it's in journald | No. The `journald` receiver needs `journalctl` |
| Control plane on kubeadm clusters | No: it runs in `kube-system` | Yes. In CI on kind, `kube-controller-manager` logs arrived |
| API server audit log | No: off by default | Yes. API server flags set when the cluster is created, and a reader pod, because only root can read the file |

**Unfiltered, the audit log is mostly noise.** Logging every request at `Metadata` level wrote 219 events
a minute on the idle cluster, about 205 KiB a minute or 290 MB a day. 58% were API discovery requests and
95% were reads. `cluster/audit-policy.yaml` drops requests that aren't for an object, leases, events,
token and permission checks, and reads by the cluster's own components. Measured idle for 5 minutes after
that: 11.8 events a minute, 13.9 KiB a minute. It still keeps every request from apps and people, and
every change by anyone.

**A policy rule with both `users` and `userGroups` needs both to match.** The first version put the
system users and groups in one rule, expecting either to match, and it matched nothing. Kubernetes'
`ruleMatches` returns false unless every field the rule sets matches. Split them into two rules.

**Only root can read the audit log.** The API server creates it with mode 0600 in a 0700 directory. The
node agents run as user 10001 in group 0, which is how they read pod logs (mode 0640), but not this file:
`permission denied`. Running the agents as root would also let them read every root-only file under the
node filesystem they mount, such as the kubelet's keys. So `labs/lab3-kubernetes/k8s/audit-log.yaml`
runs `tail -F` as root, with only the audit directory mounted read-only and all capabilities dropped,
and the agents read its output.

**Most of k3s's ERROR lines are routine.** While a worker restarted and the labs redeployed, k3s logged 52
ERROR lines in 7 minutes: 27 `RemoveStaleState: removing container`, 23 lookups of containers that were
already gone, and 2 `Failed to get system UUID`, because k3d nodes have no `/etc/machine-id`. Don't alert
on the count. At idle it writes a few lines every 5 minutes on each node.

**Restarting one k3d node changes its IP.** Restarting only the server node, to reload the audit policy,
moved it from 192.168.144.3 to .2. k3d's load balancer kept using the old address, so `kubectl` got
`EOF`, and after the next restart the worker went NotReady. Restarting the load balancer and then the
worker fixed both. `scripts/up.sh` now waits for the API server, and says what to restart if it doesn't
answer. Restarting the whole cluster instead, with `k3d cluster stop signoz-lab` and `make up`, also gave
the nodes new IPs, but everything restarts together, so nothing broke. Both smoke tests passed within 5
minutes. That's the way to apply a policy change.

**k3d 5.5.0 logs about 5,800 lines an hour on the worker node,** unseen. Its start-up script runs
`until kubectl uncordon "$HOSTNAME"; do sleep 3; done`, and worker nodes have no `kubectl` login, so it
never stops. The server node logged 81 lines in the same hour. Harmless, but these logs are how you'd
find it.

### The dashboards

All four community dashboards imported unchanged. Their Pod dashboard's namespace selector defaulted
to `default`, which has no pods, so every panel read "No data in this time range" until `lab3` was
selected.

## Alerts

Tested 2026-11-07. Lab 4's eight rules each ran against the real failure, on k3d. Times are from
causing the failure to the notification arriving at the sink.

| Rule | Signal | Failure to notification | Failure ended to resolved |
|---|---|---|---|
| Lab 1: error logs | Logs | 3m 22s | 12m 32s |
| Lab 3: killed by a liveness probe | Logs (Kubernetes event) | 3m 42s | 8m 42s |
| Lab 3: CPU throttled | Metrics, formula | 3m 57s | 6m 27s |
| Lab 1: slow database queries | Traces | 4m 01s | 8m 59s |
| Lab 3: API calls denied | Traces | 4m 03s | 8m 03s |
| Lab 3: container OOM killed | Metrics | About 4m 13s | Stays firing until the pod is replaced |
| Lab 1: error rate above 20% | Traces, formula | 4m 36s | 7m 06s |
| Lab 3: telemetry stopped | Absent metric | 6m 11s | 5m 53s |

**Where the time goes,** from SigNoz v0.149.0's source and the rule history:

- **`ruler.eval_delay`, 2 minutes.** Rules look at data that's 2 minutes old, so late data can land.
- **Evaluation every minute.** Rules entered `firing` 3 to 3.5 minutes after the failure.
- **`group_wait`, 30 seconds.** The notification followed 30 to 60 seconds later.
- **`group_interval`, 5 minutes.** Resolved notifications arrive on a 5-minute tick after the alert's
  last notification: 19:43:51 to 19:48:51, 19:47:12 to 19:52:12, 19:49:49 to 19:54:49.

**First choices that sounded right, and were wrong:**

| Choice | Problem | Fix |
|---|---|---|
| OOM alert on `container_oom_events_total` | Would never fire: it reads 0 | Restarts by `last_terminated_reason` |
| Liveness alert on the rate of `prober_probe_total` | Reads 0 for a pod's first failures | The Kubernetes event |
| 403s from `apiserver_request_total` | Would never fire: no such series | Client spans |
| Throttling above 25% | This pod's normal is 19 to 32%, so it never resolved | 50% |
| Error rate above 5%, P95 above 1 second | Always firing under the default load | 20%, and the slowest SQL call |
| Absent data with a 5-minute window | The window must empty first, so it needed about 9 minutes of silence | A 1-minute window |

**Absent-data alerts are renamed.** The rule `Lab 3: telemetry stopped` arrives as
`[No data] Lab 3: telemetry stopped`, with `nodata: true`. Anything that routes or filters by alert
name has to allow for that. A test that matched the exact name reported that this alert never fired.

**`eval_window` in SigNoz's log is misleading.** It logs 300000 for every rule, because that's a legacy
field that defaults to 5 minutes. The query uses `evaluation.spec.evalWindow`, as the timings confirm.

## Automating it

Tested 2026-11-07 on k3d with real service account keys, then deleted. Terraform wasn't run.

| Role | Read dashboards and rules | Create dashboards and rules | Create channels |
|---|---|---|---|
| None | 403 | 403 | |
| `signoz-viewer` | 200 | 403 | |
| `signoz-editor` | 200 | 201 | 403 |
| `signoz-admin` | | | 201 |

- **Keys use the `SigNoz-Api-Key` header.** A deleted key gets a 401.
- **Posting a dashboard twice creates two copies,** with a 201 each time.
- **Unknown paths return the web app with a 200,** so `curl -f` passes. A mistyped role assignment
  returned 200 and did nothing.
- **Deleted service accounts stay in the list,** marked `deleted`, with no keys or roles.
- **The Terraform provider is Untested.** Its documentation describes typed snake_case dashboards,
  so exported camelCase JSON probably can't be loaded as it is.

## Resource use

Measured 2026-11-07 with both labs running on k3d, after the tuning below:

| | Idle | Load generator at 5 requests/s |
|---|---|---|
| All pods, CPU | 0.25 to 0.3 core | 0.6 to 0.7 core |
| All pods, memory | About 4.3 GiB | About 4.4 GiB |
| ClickHouse | 0.12 to 0.17 core, 2.6 GiB | 0.23 to 0.35 core, 2.7 GiB |
| ZooKeeper | 0.02 core, 0.4 GiB | 0.03 core, 0.4 GiB |
| Docker Desktop's VM on the Mac | 0.5 to 0.9 core | 0.6 to 1.6 cores |

- **Memory is a fixed cost.** It barely changes with traffic, and most of it is ClickHouse.
- **The Docker VM costs more than the pods,** because of virtualization.
- **Other projects share that VM.** Containers from other work on the same machine were using up to
  a whole core during these tests, so the VM figures are approximate.

### What Lab 3 adds

| | Before Lab 3 | With Lab 3 |
|---|---|---|
| Samples a minute, all of SigNoz | 32,636 | 51,493 |
| ClickHouse CPU, idle | 0.12 to 0.17 core | 0.12 to 0.17 core |
| ClickHouse memory | 2.6 GiB | 3.1 GiB |
| Cluster collector memory | 67 MiB | About 220 MiB |
| All pods, memory | 4.3 GiB | 5.2 GiB |

- **The scrape jobs add about 6,000 series.** The sample count also includes Lab 3's own two pods.
- **The endpoints are far bigger than what's kept.** The API server exposes 32,461 series. On k3s the
  server node's kubelet returns almost the same 32,429, because k3s runs everything in one process
  with one metrics registry. The collector reads about 73,000 lines every 30 seconds, which is why its
  memory rose.
- **The keep-list was measured, not guessed.** A shorter one left community dashboard panels empty.
  Filling them added 17% more samples (43,848 to 51,493) with no measurable change in ClickHouse CPU
  or memory, so the lab keeps them. `apiserver_request_sli_duration_seconds` is the biggest item, at
  about 4,250 series.
- **`presets.prometheus.enabled` scrapes more than you asked for.** It also started scraping SigNoz's
  own pods, adding 5,239 series, more than double the jobs at the time. Lab 3 limits that job to
  `lab3`, which turns it off.
- **The cause of ClickHouse's memory rise isn't isolated.** It could be new data, or caching from
  opening dashboards.

### Reducing ClickHouse's own load

Two changes, both in `signoz/signoz-values.yaml`:

| | Before | After |
|---|---|---|
| ClickHouse's logs about itself | About 165,000 rows a minute | About 4,500 rows a minute |
| Writes in the test window, same load | 5,775 | 1,672 |
| CPU spent on those writes | 28.1 seconds | 7.5 seconds |
| ClickHouse CPU under load | 0.4 to 0.7 core | 0.2 to 0.3 core |
| ZooKeeper memory | 904 MiB | About 400 MiB |
| All pods, memory | About 5.4 GiB | About 4.4 GiB |

- **Turning off the self-logging didn't reduce CPU.** It saved disk and memory. In one measurement
  those logs took 1.83 GiB, against about 150 MiB of telemetry.
- **The CPU cost was the writes.** With a 1-second batch, ClickHouse took about 24 small writes a
  second. A 5-second batch cut that by 71%.
- **Other containers were quieter in the second run,** so the CPU comparison is partly confounded.
  The write counts aren't affected.
- **The Service Map improved slightly.** `lab1-frontend → lab1-backend` went from 62% to 74% of real
  calls, because a longer batch keeps more parents and children in one insert. That's one run with
  two collectors, so don't treat 74% as a fixed figure. It varied from 0 to 74% across runs.

## Not caused by SigNoz

**k3d needs a mount fix** for the agent. kind and real Kubernetes nodes do not.

## Next steps

Suggested order. Nothing here has been applied. Alerts and Kubernetes dashboards were on this list,
and are now Labs 3 and 4.

1. Remove the noisy ASGI spans. This saves more than half of stored spans and loses nothing.
2. Try trace-ID load balancing, to restore map accuracy with two collectors.
3. Add `memory_limiter`, and send the collectors' own metrics to SigNoz.
4. Remove duplicate logs (gap 4).
5. Import dashboards from `apm/` and `postgresql/`. Lab 3 already imports the Kubernetes ones.
6. Decide how far HA should go: ClickHouse, ZooKeeper, Postgres and the control plane.

`BENCHMARK.md` explains this order, and why sampling is not on the list yet.
