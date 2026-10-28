"""Proceso worker (ADR-0007): la misma imagen que el API, otro comando.

Corre el relay del outbox y el consumidor de Kafka (con KAFKA_ENABLED) y las
purgas periódicas (outbox publicado, claves de idempotencia, sesiones). Con
SIGTERM termina lo que está haciendo y se detiene en orden. Su salud está en
WORKER_HEALTH_FILE (`python -m src.shared.infra.worker.health`).

    python worker.py
"""

import dataclasses
from pathlib import Path

import structlog

import src
from config import config
from src.background.messaging import create_messaging
from src.background.tasks import periodic_tasks
from src.container import create_wireup_container
from src.shared.infra.adapters import OpenTelemetry
from src.shared.infra.logging import configure_logging
from src.shared.infra.worker.runner import Service, Worker, WorkerHealth

# Its own service name, so a sale's trace shows API → worker → invoicing
SERVICE_NAME = f"{config.OTEL_SERVICE_NAME}-worker"

# Without a cycle for this long the relay or the consumer is stuck: the relay
# polls every OUTBOX_POLL_INTERVAL_SECONDS and the consumer every second, but a
# message retrying its handler holds the consumer up to a minute or two
RELAY_MAX_AGE_SECONDS = max(60.0, config.OUTBOX_POLL_INTERVAL_SECONDS * 30)
CONSUMER_MAX_AGE_SECONDS = 300.0


def main() -> None:
    configure_logging(
        log_level=config.LOG_LEVEL,
        json_output=config.ENVIRONMENT != "local",
        service_name=SERVICE_NAME,
        service_version=config.SERVICE_VERSION,
        environment=config.OTEL_ENVIRONMENT,
    )
    logger = structlog.get_logger(__name__)

    otel = OpenTelemetry()
    otel.setup(dataclasses.replace(config.get_otel_config(), service_name=SERVICE_NAME))
    # The invoice handler opens its scope from this container
    src.wireup_container = create_wireup_container()

    health = WorkerHealth(Path(config.WORKER_HEALTH_FILE))
    services: list[Service] = []
    if config.KAFKA_ENABLED:
        health.register("outbox_relay", RELAY_MAX_AGE_SECONDS)
        health.register("kafka_consumer", CONSUMER_MAX_AGE_SECONDS)
        services.append(
            create_messaging(
                on_relay_cycle=health.reporter("outbox_relay"),
                on_consumer_cycle=health.reporter("kafka_consumer"),
            )
        )
    else:
        logger.info("worker_messaging_disabled", reason="KAFKA_ENABLED is false")

    try:
        Worker(services, periodic_tasks(), health).run()
    finally:
        otel.shutdown()


if __name__ == "__main__":
    main()
