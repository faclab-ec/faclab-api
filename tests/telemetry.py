"""Traces and logs a test records, read in memory (S7.6).

OTel accepts one global tracer provider, so the whole run shares it: the
`span_exporter` fixture (`tests/conftest.py`) installs it on first use and
clears its spans around each test. `json_logs` writes the logs as the deployed
API does (JSON lines) into a buffer. Metrics live in `tests/metrics.py`.

The helpers check only what docs/architecture/OBSERVABILITY.md fixes (span
names, kinds, attributes, parent and child, `trace_id` and `event.name` in the
logs), so a renamed internal function doesn't break them.
"""

import io
import json
import logging
from collections.abc import Generator, Sequence
from contextlib import contextmanager

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanContext

from src.shared.infra.adapters.telemetry import instrument_fastapi
from src.shared.infra.logging import configure_logging

_exporter: InMemorySpanExporter | None = None


def install_tracer_provider() -> InMemorySpanExporter:
    """The run's tracer provider, with every finished span kept in memory"""
    global _exporter
    if _exporter is None:
        _exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(_exporter))
        trace.set_tracer_provider(provider)
    return _exporter


# --- Spans --------------------------------------------------------------------


def named(spans: Sequence[ReadableSpan], name: str) -> list[ReadableSpan]:
    return [span for span in spans if span.name == name]


def one(spans: Sequence[ReadableSpan], name: str) -> ReadableSpan:
    """The only finished span with that name"""
    found = named(spans, name)
    assert len(found) == 1, f"{len(found)} spans named {name!r}: {names(spans)}"
    return found[0]


def names(spans: Sequence[ReadableSpan]) -> list[str]:
    return [span.name for span in spans]


def ids(context: SpanContext) -> tuple[str, str]:
    """Trace and span id as they travel in `traceparent` and the logs"""
    return format(context.trace_id, "032x"), format(context.span_id, "016x")


def span_ids(span: ReadableSpan) -> tuple[str, str]:
    context = span.context
    assert context is not None
    return ids(context)


def children_of(
    spans: Sequence[ReadableSpan], parent: ReadableSpan
) -> list[ReadableSpan]:
    return [span for span in spans if _is_child(span, parent)]


def descends_from(
    spans: Sequence[ReadableSpan], span: ReadableSpan, ancestor: ReadableSpan
) -> bool:
    """Whether `ancestor` is `span`'s parent, grandparent..., among `spans`"""
    by_id = {s.context.span_id: s for s in spans if s.context is not None}
    current: ReadableSpan | None = span
    while current is not None and current.parent is not None:
        if _is_child(current, ancestor):
            return True
        current = by_id.get(current.parent.span_id)
    return False


def assert_child_of(child: ReadableSpan, parent: ReadableSpan | SpanContext) -> None:
    """`child` continues `parent`'s trace with `parent` as its direct parent"""
    context = parent if isinstance(parent, SpanContext) else parent.context
    assert context is not None
    assert child.context is not None
    assert child.context.trace_id == context.trace_id, (
        f"{child.name!r} is in another trace"
    )
    assert child.parent is not None, f"{child.name!r} has no parent"
    assert child.parent.span_id == context.span_id, (
        f"{child.name!r} is not a child of the expected span"
    )


def _is_child(span: ReadableSpan, parent: ReadableSpan) -> bool:
    return (
        span.parent is not None
        and parent.context is not None
        and span.parent.span_id == parent.context.span_id
        and span.parent.trace_id == parent.context.trace_id
    )


def traceparent_ids(header: str | bytes) -> tuple[str, str]:
    """Trace id and parent span id of a W3C `traceparent` header"""
    value = header.decode() if isinstance(header, bytes) else header
    version, trace_id, span_id, _flags = value.split("-")
    assert version == "00"
    return trace_id, span_id


def traceparent_of(context: SpanContext) -> str:
    """The `traceparent` another service sends from inside that span"""
    trace_id, span_id = ids(context)
    return f"00-{trace_id}-{span_id}-01"


# --- Logs ---------------------------------------------------------------------


class JsonLogs:
    """Logs written as the deployed API writes them; call it to read the lines
    written so far"""

    def __init__(self, buffer: io.StringIO):
        self._buffer = buffer

    def __call__(self) -> list[dict]:
        return [json.loads(line) for line in self._buffer.getvalue().splitlines()]

    def of_trace(self, trace_id: str) -> list[dict]:
        return [line for line in self() if line.get("trace_id") == trace_id]

    def event(self, event: str) -> list[dict]:
        return [line for line in self() if line.get("event") == event]


@contextmanager
def json_logs() -> Generator[JsonLogs]:
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    configure_logging(
        log_level="DEBUG",
        json_output=True,
        service_name="faclab-core",
        service_version="1.2.3",
        environment="test",
    )
    # Into a buffer: the handler keeps the stream it was created with, and
    # pytest swaps sys.stdout between the phases of a test
    buffer = io.StringIO()
    for handler in root.handlers:
        if isinstance(handler, logging.StreamHandler):
            handler.setStream(buffer)
    try:
        yield JsonLogs(buffer)
    finally:
        root.handlers[:] = handlers
        root.setLevel(level)


# --- The API ------------------------------------------------------------------


@contextmanager
def instrumented(app: FastAPI) -> Generator[FastAPI]:
    """The app with the OTel middleware as its outermost one, as `main.py` adds
    it when OTel is enabled (tests run with OTEL_ENABLED=false). Starlette
    builds the middleware stack on the first request and refuses new middleware
    afterwards, so the stack is dropped and built again on both ends."""
    app.middleware_stack = None
    instrument_fastapi(app)
    try:
        yield app
    finally:
        FastAPIInstrumentor.uninstrument_app(app)
