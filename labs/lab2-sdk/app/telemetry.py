"""OpenTelemetry setup, written out by hand so every piece is visible.

This is what a developer typically writes when "just using the OTel SDK".
Nothing here is SigNoz-specific: the app speaks plain OTLP/HTTP and could send
to any OTLP backend.

Configuration comes from the standard OTel environment variables
(set in labs/lab2-sdk/k8s/app.yaml), not from code:

  OTEL_SERVICE_NAME             -> resource attribute service.name
  OTEL_RESOURCE_ATTRIBUTES      -> extra resource attributes (version, env)
  OTEL_EXPORTER_OTLP_ENDPOINT   -> where to send, e.g. http://collector:4318
  OTEL_EXPORTER_OTLP_PROTOCOL   -> http/protobuf

Signals:
  traces  -> TracerProvider + BatchSpanProcessor + OTLP exporter
  metrics -> MeterProvider + PeriodicExportingMetricReader + OTLP exporter
  logs    -> LoggerProvider + BatchLogRecordProcessor + OTLP exporter,
             bridged from Python's standard `logging` via LoggingHandler
"""

import logging
import os
import sys

from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


class _StdoutFormatter(logging.Formatter):
    """Plain-text stdout log line with trace context, like many apps print.

    These stdout lines are NOT sent over OTLP. They only matter if something
    scrapes container stdout (Phase 2: the k8s-infra chart does).
    """

    def format(self, record: logging.LogRecord) -> str:
        span_ctx = trace.get_current_span().get_span_context()
        record.trace_id = format(span_ctx.trace_id, "032x") if span_ctx.is_valid else "-"
        record.span_id = format(span_ctx.span_id, "016x") if span_ctx.is_valid else "-"
        return super().format(record)


def setup_telemetry() -> None:
    # Resource.create() merges OTEL_SERVICE_NAME and OTEL_RESOURCE_ATTRIBUTES
    # with the SDK's own telemetry.sdk.* attributes.
    resource = Resource.create()

    # --- Traces -------------------------------------------------------------
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    # --- Metrics ------------------------------------------------------------
    # Export every 10 s (SDK default is 60 s) so the lab feels responsive.
    reader = PeriodicExportingMetricReader(OTLPMetricExporter(), export_interval_millis=10_000)
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[reader]))

    # --- Logs ---------------------------------------------------------------
    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
    set_logger_provider(logger_provider)

    root = logging.getLogger()
    root.setLevel(os.getenv("LOG_LEVEL", "INFO"))
    # 1) OTLP: every stdlib log record becomes an OTel LogRecord, with the
    #    active trace_id/span_id attached automatically.
    root.addHandler(LoggingHandler(level=logging.NOTSET, logger_provider=logger_provider))
    # 2) stdout: human-readable line for `kubectl logs`.
    stdout = logging.StreamHandler(sys.stdout)
    stdout.setFormatter(
        _StdoutFormatter(
            "%(asctime)s %(levelname)s [%(name)s] trace_id=%(trace_id)s span_id=%(span_id)s %(message)s"
        )
    )
    root.addHandler(stdout)
