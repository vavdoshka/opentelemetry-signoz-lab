# Investigating the telemetry lab

You're helping investigate problems in a small Kubernetes lab that SigNoz
observes. Most agent harnesses read this file (Codex, OpenCode). Claude Code
reads it through CLAUDE.md.

This file describes the environment, like a team runbook would. It deliberately
says nothing about what has gone wrong before: find that out from the data.

## What you can use

- **SigNoz, through the `signoz` MCP server.** Traces, logs, metrics, alert rules
  and their history. The key is read-only: anything that changes SigNoz fails
  with 403. Don't try to create or change alerts, dashboards or views.
- **`kubectl get`, `describe`, `logs` and `top`.** Read-only as well: you can't
  read Secrets or ConfigMaps, exec into pods, or change anything. Run one
  command per call. A chain with `sed` or `echo` in it is refused as a whole.
- Nothing else. No web access, and no changing files.

## The environment

- Two nodes. All times are UTC.
- `lab1`: a shop with three services, `lab1-frontend` → `lab1-backend` →
  PostgreSQL. Python, instrumented automatically by the OpenTelemetry
  Operator, so they have traces, logs and runtime metrics with no code changes.
  `lab1-loadgen` sends it traffic, and isn't traced.
- `lab2`: the same shop, `frontend` → `backend` → PostgreSQL, with business
  data added by hand. The `price_order` span carries `order.item`,
  `order.qty`, `order.coupon` and `order.total`, in USD. `GET /catalog` spans
  carry `cache.hit`. The metrics `orders.created` and `orders.value` are by
  `order.item`, and `cache.lookups` by `cache.hit`. `order stored` logs carry
  `order.id`, `order.item` and `order.total`. `loadgen` sends it traffic, and isn't traced.
- `lab3`: `lab3-workload`, with limits of 200m CPU and 256Mi memory and a
  liveness probe. `lab3-loadgen` sends it traffic, and is traced, so its
  spans show failures from the caller's side.
- `lab4`: the alert sink. `lab5`: the MCP server.
- `signoz`: SigNoz itself. It's the observer, not the subject.

## Where the signals are

- App traces and logs: `service.name` is the Deployment name, such as
  `lab1-backend`. Spans and logs carry `k8s.pod.name` and `k8s.namespace.name`.
- Pod, container and node metrics come from the kubelet: `k8s.pod.*`,
  `k8s.container.*`, `k8s.node.*`. Prometheus-style metrics from the kubelet,
  cAdvisor and API server keep their own names, such as
  `container_cpu_cfs_throttled_periods_total` and `apiserver_request_total`.
- Kubernetes events are logs, with `k8s.event.reason`. Filter on them with the
  `attribute.` prefix, as in `attribute.k8s.namespace.name = 'lab3'`.
- The kernel log is the output of the `kernel-log` pods in `lab3`, including
  OOM kills. Those pods have no `service.name`, so search with
  `k8s.pod.name CONTAINS 'kernel-log'`.
- The API server's audit log: `service.name = 'kube-apiserver-audit'`, with
  `k8s.audit.user`, `k8s.audit.verb`, `k8s.audit.resource` and
  `k8s.audit.code`.
- k3s's own log on k3d: `service.name = 'k3s'`. The kubelet and containerd on
  kind: `service.name = 'kubelet'` and `'containerd'`.

## How to answer

Lead with the cause in one sentence. Then give the evidence: for each point,
the tool or query you used and the numbers it returned. Say how confident you
are, and what would confirm it. Suggest a fix, but don't apply anything.
Keep it under 300 words, and never guess a number you didn't read.
