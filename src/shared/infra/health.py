"""Liveness and readiness endpoints for the orchestrator and the reverse proxy.

They are public, hidden from the API docs and dropped from the access log, so a
check every few seconds doesn't drown the real traffic.
"""

import logging
from collections.abc import Callable, Mapping

import structlog
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

from src.shared.infra.kafka.producer import KafkaEventProducer

logger = structlog.get_logger(__name__)

HEALTH_PREFIX = "/health"

# A check returns when the dependency is usable and raises otherwise
HealthCheck = Callable[[], None]


def create_health_engine(connection_string: str) -> Engine:
    """Engine for the readiness check, with a short connect timeout so an
    unreachable database fails the check instead of hanging the request."""
    connect_args = {}
    if make_url(connection_string).get_backend_name() == "postgresql":
        connect_args["connect_timeout"] = 2
    return create_engine(
        connection_string, pool_pre_ping=True, connect_args=connect_args
    )


def database_check(engine: Engine) -> HealthCheck:
    def check() -> None:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    return check


def kafka_check(producer: KafkaEventProducer) -> HealthCheck:
    def check() -> None:
        if not producer.is_connected:
            raise ConnectionError("Kafka producer is not connected")

    return check


class HealthRouter:
    """`checks` decide readiness (503 when one fails). `informational` ones only
    turn the status into `degraded`: Kafka being down doesn't stop sales, since
    the outbox keeps the messages until it comes back."""

    def __init__(
        self,
        checks: Mapping[str, HealthCheck],
        informational: Mapping[str, HealthCheck] | None = None,
    ):
        self._checks = checks
        self._informational = informational or {}
        self.router = APIRouter(prefix=HEALTH_PREFIX, include_in_schema=False)
        self._setup_routes()

    def _setup_routes(self):
        self.router.get("/live")(self.live)
        self.router.get("/ready")(self.ready)

    def live(self) -> dict:
        return {"status": "ok"}

    def ready(self) -> JSONResponse:
        results = {name: self._run(name, check) for name, check in self._checks.items()}
        required_ok = all(result == "ok" for result in results.values())

        for name, check in self._informational.items():
            results[name] = self._run(name, check)
        all_ok = all(result == "ok" for result in results.values())

        if not required_ok:
            status, code = "unavailable", 503
        elif not all_ok:
            status, code = "degraded", 200
        else:
            status, code = "ok", 200
        return JSONResponse(
            status_code=code, content={"status": status, "checks": results}
        )

    @staticmethod
    def _run(name: str, check: HealthCheck) -> str:
        try:
            check()
        except Exception as exc:
            logger.warning("readiness_check_failed", check=name, error=str(exc))
            return "unavailable"
        return "ok"


class HealthCheckAccessFilter(logging.Filter):
    """Drops health checks from uvicorn's access log, whose records carry
    (client, method, path, http_version, status) as args."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3:
            path = args[2]
            if isinstance(path, str) and path.startswith(f"{HEALTH_PREFIX}/"):
                return False
        return True
