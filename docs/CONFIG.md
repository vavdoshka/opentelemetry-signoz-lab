# Configuration log

Every change from a default, with the reason. If it isn't listed here, it's at its default.

## Cluster

| What | Where | Why |
|---|---|---|
| Two nodes | `cluster/k3d-config.yaml`, `cluster/kind-config.yaml` | Smallest setup that tests node failure |
| k3s pinned to v1.26.4 | `cluster/k3d-config.yaml` | The version every finding was measured on. It is old, which is fine for a local lab. k3d 5.5.0 cannot start k3s v1.34.3 |
| Host port 8080 reaches the ingress | Both cluster configs | The UIs are at `*.localhost:8080` |
| Traefik installed (kind only) | `cluster/traefik-kind-values.yaml` | kind has no ingress controller. k3s ships Traefik |
| Control-plane taint removed (kind only) | `scripts/up.sh` | Lets workloads use both nodes, like k3d |
| k3s also logs to `/var/log/k3s.log` (k3d only) | `cluster/k3d-config.yaml`: `--log`, `--alsologtostderr` | k3s runs the kubelet, API server, scheduler and controller manager in one process, which logs only to `docker logs` by default. Pods can't read that, but the node agents can read a file. `--alsologtostderr` keeps `docker logs` working, and k3d needs it: it waits for k3s's startup messages there. k3s rotates the file at 50 MB and keeps 3 compressed copies |
| API server audit log | `cluster/audit-policy.yaml`, and both cluster configs | Records who made each API request. Off by default. The policy drops requests that aren't for an object (discovery, health checks, metrics), leases, events, token and permission checks, and reads by the cluster's own components. It records the rest at `Metadata` level: caller, verb, object and response code, never bodies. That took it from 219 events a minute at idle to about 12. Rotated at 20 MB, keeping 2 old files. On kind it's a kubeadm patch, plus mounts for the policy and the log directory, because the API server runs as a pod |

These last two only take effect when the cluster is created. A cluster from before them needs `make down`
and `make up`. Lab 3 collects both files; until then they're written but not read. The API server reads
the policy file when it starts, so to apply a change to it, run `k3d cluster stop signoz-lab` and
`make up`. Restarting only the server node gives it a new IP that k3d's load balancer doesn't follow.

## SigNoz

| What | Where | Why |
|---|---|---|
| `otelCollector.replicaCount: 2` | `signoz/signoz-values.yaml` | HA. Ingestion survives losing a node, but Service Map accuracy falls. See `FINDINGS.md` |
| `otelCollector.config.processors.batch.timeout: 5s` | `signoz/signoz-values.yaml` | Default 1s. Each flush writes to about a dozen tables, so fewer, larger writes cost ClickHouse much less CPU. Data appears up to 5 seconds later |
| `config.d/zz-lab-system-logs.xml` | `clickhouse.files` in `signoz/signoz-values.yaml` | Turns off five of ClickHouse's logs about itself. `query_log` and `part_log` stay, because they help diagnosis |
| `clickhouse.zookeeper.heapSize: 256` | `signoz/signoz-values.yaml` | The default 1 GB heap is far more than this lab needs |
| Ingress for `signoz.localhost` | `signoz/ingress.yaml` | UI access, kept outside the Helm release |
| First admin account | `scripts/bootstrap_signoz.py` | **Required.** The collector opens no OTLP ports until an organization exists |

The admin uses the placeholder `admin@lab.local` and a generated password, stored in
`.lab-credentials` (mode 600).

### ZooKeeper, not ClickHouse Keeper

ClickHouse has its own coordination service, [ClickHouse Keeper](https://clickhouse.com/docs/guides/sre/keeper/clickhouse-keeper),
which it describes as replacing ZooKeeper. ZooKeeper still works: this lab runs it with ClickHouse
25.12.5. SigNoz chart 0.149.0 has no Keeper option. It installs ZooKeeper 3.7.1, and the only
alternative it offers is `clickhouse.externalZookeeper`, which points at one you run yourself.
Pointing that at a Keeper is **Untested**.

[Use of Zookeeper](https://github.com/SigNoz/signoz/discussions/4671) asks whether SigNoz will
follow ClickHouse. It had no reply on 2026-11-07.

## Lab 1: hands-off

The app has no OpenTelemetry code or settings. All of its configuration is in
`labs/lab1-hands-off/k8s/instrumentation.yaml`:

| What | Why |
|---|---|
| `inject-python: "true"` on the `lab1` namespace | Opts in every pod in the namespace |
| `inject-python: "false"` on Postgres | Opts it out, because it isn't a Python app |
| `exporter.endpoint` set to the SigNoz agent | Sends to the agent on the same node |
| `sampler: parentbased_always_on` | Keeps every trace, and states the default explicitly |
| `OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED=true` | Python logs are off by default in the Operator |
| `OTEL_PYTHON_FASTAPI_EXCLUDED_URLS=healthz` | No spans for Kubernetes probes |
| `OTEL_BSP_SCHEDULE_DELAY=500` | The gap 2 fix |
| `OTEL_METRIC_EXPORT_INTERVAL=10000` | Exports metrics every 10 seconds (default 60), so the lab feels responsive |

The Operator comes from its official Helm chart. `cluster/otel-operator-values.yaml` makes the chart
generate its own webhook certificate, so the lab doesn't need cert-manager. It also sets
`recreate: false`. By default every `helm upgrade` makes a new certificate, and pods created before
the Operator loads it start without the agent, with no error.

## Lab 2: custom dimensions

Lab 2 uses the same injection as Lab 1, with its own `labs/lab2-custom-dimensions/k8s/instrumentation.yaml`.
There is no SDK setup, and its manifest has no OpenTelemetry settings. The code in
`labs/lab2-custom-dimensions/app/` uses only the OpenTelemetry API. Its requirements add
`opentelemetry-api`, and API calls do nothing if the agent isn't there.

`labs/lab2-custom-dimensions/dashboard.json` is the SigNoz dashboard `make lab2` creates.

### High availability

All in `labs/lab2-custom-dimensions/k8s/app.yaml`. Lab 1 runs one replica of each service:

| What | Why |
|---|---|
| `replicas: 2` on `frontend` and `backend` | Survive losing a node |
| `topologySpreadConstraints` with `DoNotSchedule` | Force one replica per node. `ScheduleAnyway` put them all on one node |
| `nodeTaintsPolicy: Honor` | Leave dead nodes out of the count, so a replacement can start on the survivor. Not exercised by the crash test |
| `maxSurge: 0, maxUnavailable: 1` | Keep the spread through rollouts. Costs one replica of capacity during a deploy |
| Separate `loadgen` Deployment, `LOADGEN_TARGET` env var, Ingress path `/api/load` | Its state is in-process, so it can't sit behind two replicas. One replica, so it is not HA |

Postgres stays at one replica with no persistent volume, so test orders are lost on restart.

## Lab 3: Kubernetes

The workload in `labs/lab3-kubernetes/app/` has no OpenTelemetry code, and uses the same injection as
Lab 1. `k8s/app.yaml` sets what Labs 1 and 2 don't, because these give Kubernetes a reason to act:

| What | Why |
|---|---|
| `limits: { cpu: 200m, memory: 256Mi }` | CPU above the limit is throttled, and memory above it is an OOM kill |
| `livenessProbe`, 5-second period, 3-second timeout, 3 failures | Lets the kubelet restart the container |
| `startupProbe` | Start-up is slow under a CPU limit. Holds off liveness until the app is up |
| `emptyDir` with `sizeLimit: 1Gi` | Puts the `disk` scenario's file on the node's disk, with a cap |
| `Role` allowing `list pods` in `lab3` | Only used by the `api_flood` and `api_denied` scenarios |
| Separate `lab3-loadgen` Deployment | Load keeps coming while the workload restarts |
| `kernel-log` DaemonSet, privileged, in `k8s/kernel-log.yaml` | Reads each node's `/dev/kmsg` and prints it, so the agent collects the kernel log. The collector can't read it itself |
| `journal-log` DaemonSet, in `k8s/journal-log.yaml`, kind only | Runs `journalctl` on each node's journal and prints the kubelet's and containerd's entries as JSON. The agents can read the journal's files (group 0), but their image has no `journalctl`. Runs as the agents' user and group, not root. The Lab 3 image installs Debian's `systemd` package for `journalctl`, about 5 MB |
| `audit-log` DaemonSet, root, in `k8s/audit-log.yaml` | Prints the audit log, which only root can read. The node agents run as user 10001. Running them as root would let them read every root-only file on the node, because they mount its filesystem. This pod has only the audit directory, read-only, with all capabilities dropped |

`labs/lab3-kubernetes/k8s-infra-values.yaml` adds four scrape jobs to the `k8s-infra` cluster
collector, and `k8s/metrics-rbac.yaml` gives that collector permission to read them:

| Job | Endpoint | What it adds |
|---|---|---|
| `kubelet` | each node's `:10250/metrics` | kubelet health, and its view of the container runtime |
| `cadvisor` | each node's `:10250/metrics/cadvisor` | CPU throttling |
| `kubelet-probes` | each node's `:10250/metrics/probes` | Every probe result |
| `apiserver` | the API server's `/metrics` | Requests, latency and storage objects |

- **Each job has a keep-list,** because SigNoz stores everything it's sent. See `FINDINGS.md`.
- **`presets.logsCollection.blacklist.namespaces: []`** collects `kube-system` pod logs, which the chart
  leaves out by default.
- **`otelAgent.config` adds three log receivers** on the node agents:
  - `filelog/k3s` reads `/var/log/k3s.log` through the node's `/var/log`, which the agents already
    mount. It joins multi-line messages, sets the level from each line, and sets `service.name` to `k3s`.
  - `filelog/audit` reads the `audit-log` pod's output. It copies the caller, user agent, verb,
    resource, namespace, path and response code into `k8s.audit.*` attributes, keeps the whole event
    as the body, and sets `service.name` to `kube-apiserver-audit`.
  - `filelog/journal` reads the `journal-log` pod's output, on kind. It takes the timestamp from
    journald and the level from the line, and sets `service.name` to `kubelet` or `containerd`.

  `presets.logsCollection.blacklist.containers: [audit-log, journal-log]` stops the chart's own
  receiver reading those two pods' output as well. The three run in their own `logs/node` pipeline,
  because Helm replaces lists: adding them to the chart's `logs` pipeline would mean copying its
  receiver list. All three start at the end of the file, like the chart's pod logs.
- **`presets.prometheus.namespaces: [lab3]` matters.** `presets.prometheus.enabled` also turns on an
  annotation job that scrapes SigNoz's own pods. Limiting it to `lab3` turns it off.
- **`make up` keeps these jobs.** `install_k8s_infra` in `scripts/lib.sh` adds this values file when
  namespace `lab3` exists. Without that, rerunning `make up` would remove them with no error.
- **Dashboards:** `make lab3` creates `labs/lab3-kubernetes/dashboard.json`, and imports four from
  [SigNoz/dashboards](https://github.com/SigNoz/dashboards) (Apache-2.0), pinned to one commit in
  `scripts/create_dashboard.py`.

## Lab 4: alerts

`labs/lab4-alerts/alerts.json` defines one notification channel and eight rules. `make lab4` applies
it through `/api/v2/notification_channels` and `/api/v2/rules`, then sends a test notification and
checks that it arrived. The file is the source of truth: rerunning updates rules, and removes any
labelled `lab: lab4` that it no longer lists.

`labs/lab4-alerts/app/sink.py` stands in for Slack or PagerDuty. It stores what SigNoz sends and
shows it at `lab4.localhost:8080`. To use a real service, change the channel's `config` in
`alerts.json`. SigNoz's OpenAPI file (`docs/api/openapi.yml` in its repo) has an example for each one.

## Automation

`scripts/create_dashboard.py` and `scripts/create_alerts.py` read `SIGNOZ_URL` and `SIGNOZ_API_KEY`.
With those set, they use a service account's key instead of the lab's login, so they work on any
SigNoz. `tutorial/automate.html` covers this, and `FINDINGS.md` has what was tested.

## k8s-infra

| What | Where | Why |
|---|---|---|
| `otelCollectorEndpoint` | `signoz/k8s-infra-values.yaml` | Required, no default. Must include `http://`, or pods stay Running while every export fails |
| `global.clusterName: signoz-lab` | `signoz/k8s-infra-values.yaml` | Blank by default |
| `mount --make-rshared /` in each node | `scripts/k3d-shared-mount.sh` | k3d only. See below |

### k3d mount fix

The agent mounts the host's `/` with `HostToContainer` propagation. A k3d node is a Docker
container with a private root mount, so the pod fails with:

```
path "/" is mounted on "/" but it is not a shared or slave mount
```

The script marks `/` as shared inside each node container. It is lost when a node restarts, so
`make up` always reapplies it. kind nodes and real Kubernetes nodes don't need it.

## Deliberately not changed

The gap 2 and gap 3 fixes are applied. The other fixes in `FINDINGS.md` are not:

- Labs 1 and 2 import no community dashboards and create no alerts. Labs 3 and 4 do, and no lab creates
  log pipelines.
- ASGI `send`/`receive` spans still exported.
- Duplicate logs still present.
- No trace-ID load balancing between agents and collectors.
- SigNoz's ClickHouse schema not modified.
