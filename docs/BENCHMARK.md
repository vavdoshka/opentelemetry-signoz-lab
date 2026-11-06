# Benchmark: this lab against OpenTelemetry and SigNoz guidance

Checked 2026-11-05 against the current lab: two nodes, apps sending through node agents, two SigNoz
collectors. Links to every source are at the end.

## Short answer

- **Sampling is not on by default, and this lab should not sample yet.** OpenTelemetry suggests
  considering it at about 1,000 traces per second. The lab runs at about 5.
- **Sampling would not fix the Service Map.** In SigNoz it makes counts lower, not more accurate.
- **The 41% map result breaks a general rule, not just a SigNoz quirk.** Anything that works across
  a trace needs all of that trace's spans on one collector.
- **SigNoz's documentation is uneven.** Its tail sampling guide is good. Its scaling advice says to
  add replicas without warning about this.

## Is the lab sampling?

No. Nothing drops spans at any layer:

- **SDK:** no `OTEL_TRACES_SAMPLER` is set, so the default applies: `ParentBased` with `AlwaysOn`.
- **Collectors:** no `tail_sampling` or `probabilistic_sampler` in any config.

OpenTelemetry says to consider sampling at about 1,000 or more traces per second, and says it may
not suit low-volume systems. So not sampling is correct here.

## What sampling would do to this lab's data

A read-only simulation over 6,490 real traces from the load runs. Selection used a hash of the
trace ID. No sampler was actually run.

| Policy | Traces kept | Spans kept | Error traces kept | Slow traces kept |
|---|---|---|---|---|
| No sampling | 6,490 (100%) | 64,182 (100%) | 410 of 410 | 583 of 583 |
| **No sampling, ASGI noise removed** | 6,490 (100%) | **28,394 (44%)** | **410 of 410** | **583 of 583** |
| Head 10% | 643 (10%) | 6,322 (10%) | 44 of 410 | 62 of 583 |
| Head 1% | 56 (1%) | 545 (1%) | 6 of 410 | 4 of 583 |
| Tail: errors + slow + 10% of the rest | 1,436 (22%) | 12,357 (19%) | 410 of 410 | 583 of 583 |
| Tail: errors + slow + 1% of the rest | 935 (14%) | 7,228 (11%) | 410 of 410 | 583 of 583 |

"Slow" means a span of 1 second or longer. This lab injects failures, so 6.3% of traces have errors
and 9% are slow, which is far above a healthy system. Real systems should save more from tail
sampling.

What this shows:

- **Remove noise first.** It more than halves stored spans and loses nothing.
- **Head sampling is blind.** It cannot know which traces will fail, so it drops errors at the same
  rate as everything else.
- **Tail sampling keeps what matters,** but it needs the trace-aware routing described below.

## Scorecard

| Practice | Source | Lab today | Status |
|---|---|---|---|
| Send through a Collector, not straight to the backend | OTel anti-patterns | Apps send to node agents | Meets |
| Do not sample low-volume systems | OTel sampling | No sampling at 5 requests/s | Meets |
| Small batches on agents, larger on gateways | OTel agent-to-gateway | 200 ms on agents, 1 s on collectors | Meets |
| Agents plus a gateway pool | OTel anti-patterns | Agents yes. SigNoz collectors act as the pool | Partly |
| Queue and retry on exporters | OTel agent-to-gateway | Not configured, relies on exporter defaults. The crash test kept 99.6% of traces | Partly |
| Reduce noise | SigNoz checklist | Probes excluded, but 56% of spans are ASGI noise | Partly |
| Production-suitable distribution | OTel anti-patterns | Agents use stock `contrib`, fine for a lab | Partly |
| All spans of a trace on one collector | OTel scaling, tail sampling, service graph | Plain Service, so traces split across collectors | **Misses** |
| Do not rely on L4 balancing for persistent connections | OTel scaling (written for gRPC) | One collector took every span in one run | **Misses** |
| `memory_limiter` as the first processor | OTel agent-to-gateway | Absent from agents and collectors | **Misses** |
| Monitor the collectors themselves | OTel anti-patterns | 0 `otelcol` metrics in SigNoz | **Misses** |
| Replicated ClickHouse and ZooKeeper | SigNoz distributed ClickHouse | Single instances | **Misses** |

`OTEL_BSP_SCHEDULE_DELAY=500` appears in no guidance I read. It is a workaround for how SigNoz
builds the Service Map, not a best practice.

## How SigNoz's documentation compares

**Good:**

- The tail sampling guide recommends a trace-ID routing layer, covers memory and late spans, and
  warns plainly that APM metrics "cover only the sampled traces". SigNoz says it plans to address
  this.
- There is a guide for distributed ClickHouse.

**Missing:**

- The production checklist says to "Add replicas as ingestion volume grows", and the sizing page
  lists 3 collectors. Neither mentions trace-aware routing or the Service Map. Following that advice
  is what took this lab's map from 84% to 41%.
- I found nothing on the same-insert limit behind the Services list and Service Map. This was not
  an exhaustive search.

**OpenTelemetry is clearer on the general rule.** Its service graph connector has the same
requirement: "All spans for a given request must be sent to the same collector instance."

## The trade-off OpenTelemetry describes

Tail sampling across several gateways is described as "an advanced setup", with this advice:
"prefer a single well-resourced tail-sampling gateway unless you have a robust sticky-routing
strategy." So a tail-sampling tier and HA pull against each other. The load balancing exporter also
does not re-route after a delivery failure by default, and a change in backends moves some traces to
another collector.

## Recommended architecture

```
app (SDK, keep everything)
  └─► agent, one per node: memory_limiter, k8sattributes, batch,
      loadbalancing exporter keyed on trace ID
        └─► SigNoz collectors (2+) ─► ClickHouse (replicated)

Later, only if volume requires it, add between agents and SigNoz:
  gateway: memory_limiter, tail_sampling (errors + slow + a percentage), batch
```

Applying this to the Service Map is my inference. OpenTelemetry documents trace-ID routing for tail
sampling, span metrics and service graphs, not for SigNoz's map specifically. It needs testing.

## Recommended order

1. Remove ASGI noise spans. Biggest saving, no loss.
2. Add trace-ID routing in the agents, then rerun the same map measurement.
3. Add `memory_limiter`, and send collector metrics to SigNoz.
4. Add tail sampling only if volume or cost requires it. Expect understated APM counts until SigNoz
   addresses that.
5. Plan replicated ClickHouse and ZooKeeper for real production.

## Sources

**OpenTelemetry**

- [Sampling](https://opentelemetry.io/docs/concepts/sampling/)
- [Scaling the Collector](https://opentelemetry.io/docs/collector/scaling/)
- [Gateway deployment pattern](https://opentelemetry.io/docs/collector/deploy/gateway/)
- [Agent-to-gateway deployment pattern](https://opentelemetry.io/docs/collector/deploy/other/agent-to-gateway/)
- [Collector anti-patterns](https://opentelemetry.io/blog/2024/otel-collector-anti-patterns/)
- [Load balancing exporter](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/exporter/loadbalancingexporter/README.md)
- [Tail sampling processor](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/processor/tailsamplingprocessor/README.md)
- [Service graph connector](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/connector/servicegraphconnector/README.md)
- [Span metrics connector](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/connector/spanmetricsconnector/README.md)

**SigNoz**

- [Tail sampling guide](https://signoz.io/docs/traces-management/guides/tail-sampling/)
- [Production readiness checklist](https://signoz.io/docs/production-readiness/)
- [Resources planning](https://signoz.io/docs/setup/capacity-planning/community/resources-planning/)
- [Distributed ClickHouse on Kubernetes](https://signoz.io/docs/manage/administrator-guide/clickhouse/distributed-clickhouse/kubernetes/)
