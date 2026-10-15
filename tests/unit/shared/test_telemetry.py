from opentelemetry import trace
from opentelemetry.sdk.trace.sampling import Decision
from opentelemetry.trace import NonRecordingSpan, SpanContext, SpanKind, TraceFlags

from config.base import OpenTelemetryConfig
from src.shared.infra.adapters.telemetry import create_resource, create_sampler

TRACE_ID = 0x4BF92F3577B34DA6A3CE929D0E0E4736


def _decision(kind: SpanKind, parent_sampled: bool | None = None) -> Decision:
    context = None
    if parent_sampled is not None:
        flags = TraceFlags(TraceFlags.SAMPLED if parent_sampled else 0)
        parent = SpanContext(TRACE_ID, 0x00F067AA0BA902B7, False, flags)
        context = trace.set_span_in_context(NonRecordingSpan(parent))
    result = create_sampler(1.0).should_sample(context, TRACE_ID, "span", kind)
    return result.decision


def test_a_query_outside_any_request_starts_no_trace():
    # The outbox relay polling and the readiness check
    assert _decision(SpanKind.CLIENT) == Decision.DROP


def test_requests_and_messages_start_traces():
    assert _decision(SpanKind.SERVER) == Decision.RECORD_AND_SAMPLE
    assert _decision(SpanKind.PRODUCER) == Decision.RECORD_AND_SAMPLE
    assert _decision(SpanKind.INTERNAL) == Decision.RECORD_AND_SAMPLE


def test_a_query_follows_the_decision_of_its_parent():
    assert _decision(SpanKind.CLIENT, parent_sampled=True) == Decision.RECORD_AND_SAMPLE
    assert _decision(SpanKind.CLIENT, parent_sampled=False) == Decision.DROP


def test_the_resource_names_the_service_version_and_environment():
    resource = create_resource(
        OpenTelemetryConfig(
            service_name="faclab-core",
            service_version="abc1234",
            otlp_endpoint="http://collector:4317",
            environment="staging",
        )
    )

    assert resource.attributes["service.name"] == "faclab-core"
    assert resource.attributes["service.namespace"] == "faclab"
    assert resource.attributes["service.version"] == "abc1234"
    assert resource.attributes["deployment.environment.name"] == "staging"
