import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from src.shared.infra.health import (
    HealthCheckAccessFilter,
    HealthRouter,
    database_check,
    kafka_check,
)
from src.shared.infra.kafka.producer import KafkaEventProducer


def _ok() -> None:
    return None


def _down() -> None:
    raise ConnectionError("down")


def _client(checks, informational=None) -> TestClient:
    app = FastAPI()
    app.include_router(HealthRouter(checks, informational).router)
    return TestClient(app)


def test_live_answers_without_running_checks():
    response = _client({"database": _down}).get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_when_every_check_passes():
    response = _client({"database": _ok}, {"kafka": _ok}).get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"database": "ok", "kafka": "ok"},
    }


def test_ready_is_degraded_when_only_an_informational_check_fails():
    response = _client({"database": _ok}, {"kafka": _down}).get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "degraded",
        "checks": {"database": "ok", "kafka": "unavailable"},
    }


def test_not_ready_when_a_required_check_fails():
    response = _client({"database": _down}, {"kafka": _ok}).get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "checks": {"database": "unavailable", "kafka": "ok"},
    }


def test_health_routes_are_hidden_from_the_schema():
    client = _client({"database": _ok})

    assert client.get("/openapi.json").json().get("paths", {}) == {}


def test_database_check_runs_a_query():
    database_check(create_engine("sqlite://"))()


def test_database_check_fails_when_the_database_cannot_be_opened(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/missing/dir/db.sqlite")
    client = _client({"database": database_check(engine)})

    assert client.get("/health/ready").status_code == 503


def test_kafka_check_fails_until_the_producer_connects():
    producer = KafkaEventProducer("localhost:9092")
    client = _client({"database": _ok}, {"kafka": kafka_check(producer)})

    assert client.get("/health/ready").json()["checks"]["kafka"] == "unavailable"


def _access_record(path: str) -> logging.LogRecord:
    return logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:5000", "GET", path, "1.1", 200),
        None,
    )


def test_access_log_drops_health_checks():
    access_filter = HealthCheckAccessFilter()

    assert access_filter.filter(_access_record("/health/live")) is False
    assert access_filter.filter(_access_record("/health/ready")) is False
    assert access_filter.filter(_access_record("/api/admin/products")) is True
    assert access_filter.filter(_access_record("/healthy")) is True
