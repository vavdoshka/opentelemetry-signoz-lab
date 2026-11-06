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

## SigNoz

| What | Where | Why |
|---|---|---|
| `otelCollector.replicaCount: 2` | `signoz/signoz-values.yaml` | HA, and **the only chart override.** Ingestion survives losing a node, but Service Map accuracy falls. See `FINDINGS.md` |
| Ingress for `signoz.localhost` | `k8s/signoz-ingress.yaml` | UI access, kept outside the Helm release |
| First admin account | `scripts/bootstrap_signoz.py` | **Required.** The collector opens no OTLP ports until an organization exists |

The admin uses the placeholder `admin@lab.local` and a generated password, stored in
`.lab-credentials` (mode 600).

## Application

OpenTelemetry setup is in `app/telemetry.py`. Instrumentation is added in `app/frontend.py` and
`app/backend.py`. Runtime settings are standard env vars in `k8s/app.yaml`:

| Variable | Value | Why |
|---|---|---|
| `OTEL_SERVICE_NAME` | `frontend`, `backend`, `loadgen` | Names the service |
| `OTEL_RESOURCE_ATTRIBUTES` | `service.version=0.1.0,deployment.environment=lab` | Version and environment filter |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://k8s-infra-otel-agent.signoz.svc.cluster.local:4318` | Send to the agent on the same node, which adds pod and node attributes (gap 3) |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `http/protobuf` | OTLP over HTTP, no gRPC dependency |
| `OTEL_PYTHON_FASTAPI_EXCLUDED_URLS` | `healthz` | No spans for Kubernetes probes |
| `OTEL_BSP_SCHEDULE_DELAY` | `500` | Flush spans every 500 ms (default 5000), so parent and child spans reach SigNoz in the same insert (gap 2). Without it, Services and the Service Map are unreliable |

One non-default in code: metrics export every 10 seconds (SDK default 60), so the lab feels
responsive.

### High availability

All in `k8s/app.yaml`:

| What | Why |
|---|---|
| `replicas: 2` on `frontend` and `backend` | Survive losing a node |
| `topologySpreadConstraints` with `DoNotSchedule` | Force one replica per node. `ScheduleAnyway` put them all on one node |
| `nodeTaintsPolicy: Honor` | Leave dead nodes out of the count, so a replacement can start on the survivor. Not exercised by the crash test |
| `maxSurge: 0, maxUnavailable: 1` | Keep the spread through rollouts. Costs one replica of capacity during a deploy |
| Separate `loadgen` Deployment, `LOADGEN_TARGET` env var, Ingress path `/api/load` | Its state is in-process, so it can't sit behind two replicas. One replica, so it is not HA |

Postgres stays at one replica with no persistent volume, so test orders are lost on restart.

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

- No dashboards imported, and no alerts, channels or log pipelines created.
- ASGI `send`/`receive` spans still exported.
- Duplicate logs still present.
- No trace-ID load balancing between agents and collectors.
- SigNoz's ClickHouse schema not modified.
