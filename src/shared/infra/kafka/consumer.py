"""Consume topics de Kafka en un hilo del proceso de la API.

Lo arranca el lifespan cuando KAFKA_ENABLED. Cada mensaje va al handler de su
topic y el offset se confirma solo cuando el handler termina bien: un mensaje
puede llegar más de una vez, así que los handlers deben ser idempotentes. Si el
handler falla, el consumidor vuelve a ese offset y lo reintenta tras
`retry_delay`, sin saltarse mensajes ni alterar el orden de la partición. Un
mensaje que no es un objeto JSON se descarta.
"""

import asyncio
import json
import threading
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import structlog
from aiokafka import AIOKafkaConsumer, TopicPartition
from aiokafka.errors import KafkaError
from opentelemetry import trace
from opentelemetry.propagate import extract

from src.shared.infra.telemetry_instruments import (
    kafka_consume_errors,
    kafka_messages_consumed,
)

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

MessageHandler = Callable[[dict[str, Any]], None]


class KafkaMessageConsumer:
    def __init__(
        self,
        bootstrap_servers: str,
        group_id: str,
        handlers: Mapping[str, MessageHandler],
        retry_delay: float = 5.0,
    ) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._group_id = group_id
        self._handlers = dict(handlers)
        self._retry_delay = retry_delay
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[None] | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return

        self._loop = asyncio.new_event_loop()
        self._task = self._loop.create_task(self._consume())
        self._thread = threading.Thread(
            target=self._run,
            args=(self._loop, self._task),
            daemon=True,
            name="kafka-consumer",
        )
        self._thread.start()

    def stop(self) -> None:
        if self._loop is None or self._task is None:
            return

        self._loop.call_soon_threadsafe(self._task.cancel)
        if self._thread is not None:
            self._thread.join(timeout=10)
        logger.info("kafka_consumer_stopped")

    @staticmethod
    def _run(loop: asyncio.AbstractEventLoop, task: asyncio.Task[None]) -> None:
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(task)
        except asyncio.CancelledError:
            pass
        finally:
            loop.close()

    async def _consume(self) -> None:
        # Si Kafka no está disponible, reintenta en vez de dejar el hilo muerto
        while True:
            consumer = AIOKafkaConsumer(
                *self._handlers,
                bootstrap_servers=self._bootstrap_servers,
                group_id=self._group_id,
                enable_auto_commit=False,
                auto_offset_reset="earliest",
            )
            try:
                await consumer.start()
                logger.info(
                    "kafka_consumer_started",
                    topics=list(self._handlers),
                    group_id=self._group_id,
                )
                async for record in consumer:
                    partition = TopicPartition(record.topic, record.partition)
                    if self.process(
                        record.topic,
                        record.value,
                        record.headers,
                        partition=record.partition,
                        offset=record.offset,
                    ):
                        await consumer.commit({partition: record.offset + 1})
                    else:
                        consumer.seek(partition, record.offset)
                        await asyncio.sleep(self._retry_delay)
            except KafkaError as exc:
                logger.warning(
                    "kafka_consumer_error", error=str(exc), retry_in=self._retry_delay
                )
            finally:
                await consumer.stop()
            await asyncio.sleep(self._retry_delay)

    def process(
        self,
        topic: str,
        value: bytes | None,
        headers: Sequence[tuple[str, bytes]] = (),
        partition: int | None = None,
        offset: int | None = None,
    ) -> bool:
        """Entrega el mensaje a su handler; devuelve False si hay que reintentarlo."""
        try:
            message = json.loads(value) if value is not None else None
        except ValueError:
            message = None
        if not isinstance(message, dict):
            logger.error("kafka_message_discarded", topic=topic, reason="not JSON")
            return True

        attributes: dict[str, str | int] = {
            "messaging.system": "kafka",
            "messaging.operation.type": "process",
            "messaging.operation.name": "process",
            "messaging.destination.name": topic,
            "messaging.consumer.group.name": self._group_id,
        }
        if partition is not None:
            attributes["messaging.destination.partition.id"] = str(partition)
        if offset is not None:
            attributes["messaging.kafka.offset"] = offset

        # Child of the producer's span, so the message continues its trace
        carrier = {key: raw.decode("utf-8", "replace") for key, raw in headers}
        with tracer.start_as_current_span(
            f"process {topic}",
            context=extract(carrier),
            kind=trace.SpanKind.CONSUMER,
            attributes=attributes,
        ) as span:
            try:
                self._handlers[topic](message)
            except Exception as exc:
                kafka_consume_errors.add(1, {"kafka.topic": topic})
                logger.exception("kafka_message_failed", topic=topic)
                span.record_exception(exc)
                span.set_status(trace.StatusCode.ERROR, type(exc).__name__)
                return False
        kafka_messages_consumed.add(1, {"kafka.topic": topic})
        return True
