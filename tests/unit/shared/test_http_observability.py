"""Request → log → span correlation, with the API's real middleware order."""

import uuid

import pytest
import structlog
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.trace import SpanKind, StatusCode
from pydantic import BaseModel, Field
from sqlalchemy import text

import main
from src.shared.domain.exceptions import NotFoundError
from src.shared.infra.adapters.telemetry import OpenTelemetry, instrument_fastapi
from src.shared.infra.database import create_session_maker

REQUEST_ID = "6f1c2a3e-8a3b-4c5d-9e0f-1a2b3c4d5e6f"

logger = structlog.get_logger("tests.http")


class LoginBody(BaseModel):
    username: str
    password: str = Field(min_length=12)


def _app(session_maker=None) -> FastAPI:
    app = FastAPI()

    @app.get("/items/{item_id}")
    def get_item(item_id: int) -> dict:
        logger.info("item_lookup", item_id=item_id)
        raise NotFoundError(f"Item {item_id} not found")

    @app.post("/login")
    def login(body: LoginBody) -> dict:
        # A careless log of the whole body: the redaction must still hide it
        logger.info("login_attempt", body=body.model_dump())
        return {"ok": True}

    @app.get("/query")
    def query() -> dict:
        assert session_maker is not None
        with session_maker() as session:
            session.execute(text("SELECT 1"))
        return {"ok": True}

    main.add_middlewares(app)
    instrument_fastapi(app)
    return app


def _server_span(span_exporter):
    return next(
        s for s in span_exporter.get_finished_spans() if s.kind == SpanKind.SERVER
    )


def test_a_request_log_carries_its_trace_request_and_service(span_exporter, json_logs):
    TestClient(_app()).get("/items/7", headers={"X-Request-Id": REQUEST_ID})

    line = next(line for line in json_logs() if line["event"] == "item_lookup")
    server = _server_span(span_exporter)
    assert line["trace_id"] == format(server.context.trace_id, "032x")
    assert line["span_id"] == format(server.context.span_id, "016x")
    assert line["http.request.id"] == REQUEST_ID
    assert line["event.name"] == "item.lookup"
    assert line["service.version"] == "1.2.3"
    assert line["deployment.environment.name"] == "test"


def test_a_domain_404_is_not_an_error_of_the_request_span(span_exporter, json_logs):
    response = TestClient(_app()).get("/items/7")

    assert response.status_code == 404
    server = _server_span(span_exporter)
    assert server.status.status_code == StatusCode.UNSET
    assert server.attributes is not None
    assert server.attributes["http.response.status_code"] == 404
    assert server.attributes["faclab.error.code"] == "NOT_FOUND"
    domain_error = next(line for line in json_logs() if line["event"] == "domain_error")
    assert domain_error["level"] == "warning"


def test_a_valid_request_id_is_kept_and_returned(span_exporter):
    response = TestClient(_app()).get("/items/7", headers={"X-Request-Id": REQUEST_ID})

    assert response.headers["x-request-id"] == REQUEST_ID
    assert response.json()["meta"]["requestId"] == REQUEST_ID
    server = _server_span(span_exporter)
    assert server.attributes is not None
    assert server.attributes["http.request.id"] == REQUEST_ID


@pytest.mark.parametrize("sent", [None, "req-1", "abc\nforged log line"])
def test_a_missing_or_invalid_request_id_is_replaced(sent, span_exporter):
    headers = {"X-Request-Id": sent} if sent else {}

    response = TestClient(_app()).get("/items/7", headers=headers)

    returned = response.headers["x-request-id"]
    assert returned != sent
    assert str(uuid.UUID(returned)) == returned
    assert response.json()["meta"]["requestId"] == returned


def test_passwords_tokens_and_authorization_never_reach_a_log(span_exporter, json_logs):
    client = TestClient(_app())
    headers = {"Authorization": "Bearer leaked-access-token"}

    # Rejected by validation (too short): the error logs where, never the input
    client.post(
        "/login", json={"username": "ana", "password": "Sh0rtPw"}, headers=headers
    )
    # Accepted and logged on purpose by the route
    client.post(
        "/login",
        json={"username": "ana", "password": "L0ng-enough-pass"},
        headers=headers,
    )

    lines = json_logs()
    assert any(line["event"] == "request_validation_error" for line in lines)
    attempt = next(line for line in lines if line["event"] == "login_attempt")
    assert attempt["body"] == {"username": "ana", "password": "[REDACTED]"}
    written = str(lines)
    spans = str([s.attributes for s in span_exporter.get_finished_spans()])
    for secret in ("Sh0rtPw", "L0ng-enough-pass", "leaked-access-token"):
        assert secret not in written
        assert secret not in spans


@pytest.fixture
def traced_session_maker(monkeypatch):
    # As if OTel were set up: the requests' engine gets instrumented
    monkeypatch.setattr(OpenTelemetry, "_initialized", True)
    monkeypatch.setattr(OpenTelemetry, "_engine_instrumented", False)
    yield create_session_maker("sqlite://", traced=True)
    SQLAlchemyInstrumentor().uninstrument()


def test_queries_are_spans_of_the_request(span_exporter, traced_session_maker):
    TestClient(_app(traced_session_maker)).get("/query")

    spans = span_exporter.get_finished_spans()
    server = _server_span(span_exporter)
    query = next(
        s for s in spans if (s.attributes or {}).get("db.statement") == "SELECT 1"
    )
    assert query.kind == SpanKind.CLIENT
    assert query.context.trace_id == server.context.trace_id
    assert query.parent is not None
    assert query.parent.span_id == server.context.span_id
