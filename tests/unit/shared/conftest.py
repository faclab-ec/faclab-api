import io
import json
import logging
from collections.abc import Iterator

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from src.shared.infra.logging import configure_logging

_exporter = InMemorySpanExporter()


@pytest.fixture(scope="session")
def _tracer_provider() -> TracerProvider:
    # OTel accepts the global provider only once, so the whole run shares it
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(_exporter))
    trace.set_tracer_provider(provider)
    return provider


@pytest.fixture
def span_exporter(_tracer_provider) -> Iterator[InMemorySpanExporter]:
    """Spans finished during the test, kept in memory."""
    _exporter.clear()
    yield _exporter
    _exporter.clear()


@pytest.fixture
def json_logs():
    """Logs as the deployed API writes them (JSON lines); call the fixture to
    read the lines written so far."""
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

    def read() -> list[dict]:
        return [json.loads(line) for line in buffer.getvalue().splitlines()]

    yield read
    root.handlers[:] = handlers
    root.setLevel(level)
