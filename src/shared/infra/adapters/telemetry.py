import logging
import os
from collections.abc import Sequence

import structlog
from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import (
    Decision,
    ParentBased,
    Sampler,
    SamplingResult,
    TraceIdRatioBased,
)
from opentelemetry.trace import Link, SpanKind, TraceState
from opentelemetry.util.types import Attributes
from sqlalchemy import Engine

from config.base import OpenTelemetryConfig

logger = structlog.get_logger(__name__)

# Stable HTTP conventions (http.response.status_code, http.route...). The
# instrumentations read it once, the first time one of them starts, so it is
# set on import, before any of them
os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "http")

SERVICE_NAMESPACE = "faclab"

# Probes hit these every few seconds; a trace each would drown the real traffic
EXCLUDED_URLS = "health/live,health/ready"


class SkipBackgroundQueries(Sampler):
    """Root sampler that starts no trace for a client call without a parent.

    In the core those are database queries and connections outside any request
    or message: the outbox relay polling every few seconds and the readiness
    check. Queries inside a request follow their parent's decision instead.
    """

    def __init__(self, delegate: Sampler):
        self._delegate = delegate

    def should_sample(
        self,
        parent_context: Context | None,
        trace_id: int,
        name: str,
        kind: SpanKind | None = None,
        attributes: Attributes = None,
        links: Sequence[Link] | None = None,
        trace_state: TraceState | None = None,
    ) -> SamplingResult:
        if kind == SpanKind.CLIENT:
            return SamplingResult(Decision.DROP)
        return self._delegate.should_sample(
            parent_context, trace_id, name, kind, attributes, links, trace_state
        )

    def get_description(self) -> str:
        return f"SkipBackgroundQueries{{{self._delegate.get_description()}}}"


def create_sampler(sampling_rate: float) -> Sampler:
    return ParentBased(root=SkipBackgroundQueries(TraceIdRatioBased(sampling_rate)))


def create_resource(config: OpenTelemetryConfig) -> Resource:
    return Resource.create(
        {
            "service.name": config.service_name,
            "service.namespace": SERVICE_NAMESPACE,
            "service.version": config.service_version,
            "deployment.environment.name": config.environment,
        }
    )


def instrument_fastapi(
    app: FastAPI,
    tracer_provider: trace.TracerProvider | None = None,
    meter_provider: metrics.MeterProvider | None = None,
) -> None:
    """Add the OTel middleware as the outermost one: call it after every
    `app.add_middleware`, so the error middleware runs inside the request span
    and the span ends with the final status code."""
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        excluded_urls=EXCLUDED_URLS,
    )


class OpenTelemetry:
    _instance: "OpenTelemetry | None" = None
    _initialized: bool = False
    _engine_instrumented: bool = False
    _tracer_provider: TracerProvider | None = None
    _meter_provider: MeterProvider | None = None
    _logger_provider: LoggerProvider | None = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _setup_traces(self, resource: Resource, config: OpenTelemetryConfig) -> None:
        self._tracer_provider = TracerProvider(
            resource=resource, sampler=create_sampler(config.sampling_rate)
        )
        exporter = OTLPSpanExporter(
            endpoint=config.otlp_endpoint, insecure=config.insecure
        )
        self._tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(self._tracer_provider)

    def _setup_metrics(self, resource: Resource, config: OpenTelemetryConfig) -> None:
        exporter = OTLPMetricExporter(
            endpoint=config.otlp_endpoint, insecure=config.insecure
        )
        reader = PeriodicExportingMetricReader(exporter, export_interval_millis=15000)
        self._meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
        metrics.set_meter_provider(self._meter_provider)

    def _setup_logging(self, resource: Resource, config: OpenTelemetryConfig) -> None:
        self._logger_provider = LoggerProvider(resource=resource)
        set_logger_provider(self._logger_provider)

        log_exporter = OTLPLogExporter(
            endpoint=config.otlp_endpoint, insecure=config.insecure
        )
        self._logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(log_exporter)
        )
        handler = LoggingHandler(
            level=logging.NOTSET, logger_provider=self._logger_provider
        )
        logging.getLogger().addHandler(handler)

    def setup(self, config: OpenTelemetryConfig) -> None:
        """Configure the trace, metric and log providers. Call it before
        creating the database engine and the app, so both are instrumented
        against these providers."""
        if not config.enabled:
            logger.info("otel_disabled")
            return

        if self._initialized:
            logger.info("otel_already_initialized")
            return

        try:
            resource = create_resource(config)
            self._setup_traces(resource, config)
            self._setup_metrics(resource, config)
            self._setup_logging(resource, config)
            self._initialized = True
            logger.info("otel_initialized")
        except Exception as e:
            logger.error("otel_initialization_failed", error=str(e))

    def instrument_app(self, app: FastAPI) -> None:
        if self._initialized:
            instrument_fastapi(app)

    def instrument_engine(self, engine: Engine) -> None:
        """Trace the queries of this engine (the one behind the requests)."""
        if self._initialized and not self._engine_instrumented:
            SQLAlchemyInstrumentor().instrument(engine=engine)
            self._engine_instrumented = True

    def shutdown(self) -> None:
        if not self._initialized:
            return

        if self._tracer_provider:
            self._tracer_provider.shutdown()
        if self._meter_provider:
            self._meter_provider.shutdown()
        if self._logger_provider:
            self._logger_provider.shutdown()

        logger.info("otel_shutdown")
