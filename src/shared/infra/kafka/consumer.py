"""Consume topics de Kafka en un hilo del proceso worker (o del API, con
RUN_BACKGROUND).

Cada mensaje va al handler de su topic y el offset se confirma cuando el handler
termina bien: un mensaje puede llegar más de una vez, así que los handlers deben
ser idempotentes. Si el handler falla, se reintenta con backoff exponencial
(`retry_base_delay`, con tope `retry_max_delay`) hasta `max_attempts`, sin pasar
al siguiente de la partición. Al agotarlos, el mensaje se guarda en
`dead_letters` con sus headers y el error, y se confirma su offset para que la
partición siga. Si tampoco se puede guardar (la base caída), el consumidor
vuelve a ese offset y lo intenta de nuevo tras `retry_delay`: el mensaje no se
pierde. Un mensaje que no es un objeto JSON se descarta.

El handler corre en la empresa del mensaje: el header `faclab-tenant-id` o, si
no viene, el campo `tenant_id` del sobre. Un mensaje sin empresa se procesa sin
contexto; uno con una empresa que no es un UUID se descarta.
"""

import asyncio
import json
import threading
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol
from uuid import UUID

import structlog
from aiokafka import AIOKafkaConsumer, TopicPartition
from aiokafka.errors import KafkaError
from opentelemetry import trace
from opentelemetry.propagate import extract

from src.shared.domain.tenant import TenantContext, TenantSource
from src.shared.infra.kafka.dead_letters import DeadLetter
from src.shared.infra.telemetry_instruments import (
    kafka_consume_errors,
    kafka_messages_consumed,
)
from src.shared.infra.tenant import TENANT_HEADER, tenant_scope

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

MessageHandler = Callable[[dict[str, Any]], None]


class InvalidTenantError(ValueError):
    pass


class DeadLetterSink(Protocol):
    def record(self, letter: DeadLetter) -> None:
        """Keep the message; raise if it can't be kept"""
        ...


def message_tenant(
    carrier: Mapping[str, str], message: Mapping[str, Any]
) -> UUID | None:
    """The tenant a message belongs to: its header, or its envelope's
    `tenant_id`; None when it carries neither."""
    value = carrier.get(TENANT_HEADER) or message.get("tenant_id")
    if value is None:
        return None
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise InvalidTenantError(str(value)) from exc


class KafkaMessageConsumer:
    def __init__(
        self,
        bootstrap_servers: str,
        group_id: str,
        handlers: Mapping[str, MessageHandler],
        dead_letters: DeadLetterSink | None = None,
        max_attempts: int = 5,
        retry_base_delay: float = 2.0,
        retry_max_delay: float = 60.0,
        retry_delay: float = 5.0,
        on_cycle: Callable[[], None] | None = None,
    ) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._group_id = group_id
        self._handlers = dict(handlers)
        # Without a sink a failing message is retried until it works
        self._dead_letters = dead_letters
        self._max_attempts = max_attempts
        self._retry_base_delay = retry_base_delay
        self._retry_max_delay = retry_max_delay
        self._retry_delay = retry_delay
        # Called after each poll, with messages or not (worker health)
        self._on_cycle = on_cycle
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
                while True:
                    batches = await consumer.getmany(timeout_ms=1000)
                    for partition, records in batches.items():
                        await self._consume_partition(consumer, partition, records)
                    if self._on_cycle is not None:
                        self._on_cycle()
            except KafkaError as exc:
                logger.warning(
                    "kafka_consumer_error", error=str(exc), retry_in=self._retry_delay
                )
            finally:
                await consumer.stop()
            await asyncio.sleep(self._retry_delay)

    async def _consume_partition(
        self,
        consumer: AIOKafkaConsumer,
        partition: TopicPartition,
        records: Sequence[Any],
    ) -> None:
        for record in records:
            if await self.handle(
                record.topic,
                record.value,
                record.headers,
                partition=record.partition,
                offset=record.offset,
                key=record.key,
            ):
                await consumer.commit({partition: record.offset + 1})
            else:
                # The rest of the batch comes again from this offset
                consumer.seek(partition, record.offset)
                await asyncio.sleep(self._retry_delay)
                return

    async def handle(
        self,
        topic: str,
        value: bytes | None,
        headers: Sequence[tuple[str, bytes]] = (),
        partition: int = 0,
        offset: int = 0,
        key: bytes | None = None,
    ) -> bool:
        """Processes a message with its retries; True when its offset can be
        committed (processed or kept in dead_letters)."""
        error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                self.dispatch(topic, value, headers, partition, offset)
                return True
            except Exception as exc:
                error = exc
            if attempt < self._max_attempts:
                delay = min(
                    self._retry_base_delay * 2 ** (attempt - 1), self._retry_max_delay
                )
                logger.warning(
                    "kafka_message_retry",
                    topic=topic,
                    offset=offset,
                    attempts=attempt,
                    retry_in=delay,
                )
                # Not time.sleep: the consumer's heartbeat runs in this loop
                await asyncio.sleep(delay)
        assert error is not None
        return self._dead_letter(topic, value, headers, partition, offset, key, error)

    def _dead_letter(
        self,
        topic: str,
        value: bytes | None,
        headers: Sequence[tuple[str, bytes]],
        partition: int,
        offset: int,
        key: bytes | None,
        error: Exception,
    ) -> bool:
        if self._dead_letters is None:
            return False
        carrier = _carrier(headers)
        try:
            self._dead_letters.record(
                DeadLetter(
                    consumer_group=self._group_id,
                    topic=topic,
                    partition=partition,
                    offset=offset,
                    key=key.decode("utf-8", "replace") if key is not None else None,
                    tenant_id=_tenant_of(carrier, value),
                    headers=carrier,
                    value=value.decode("utf-8", "replace")
                    if value is not None
                    else None,
                    error=str(error) or type(error).__name__,
                    attempts=self._max_attempts,
                )
            )
        except Exception:
            logger.exception("dead_letter_write_failed", topic=topic, offset=offset)
            return False
        logger.error(
            "kafka_message_dead_lettered",
            hint=(
                f"A message of {topic} failed {self._max_attempts} times and is "
                "kept in dead_letters; reprocess it with "
                "`python -m src.background.cli dead-letter-reprocess <id>`"
            ),
            topic=topic,
            partition=partition,
            offset=offset,
            attempts=self._max_attempts,
            error=str(error),
        )
        return True

    def process(
        self,
        topic: str,
        value: bytes | None,
        headers: Sequence[tuple[str, bytes]] = (),
        partition: int | None = None,
        offset: int | None = None,
    ) -> bool:
        """Entrega el mensaje a su handler, una vez; devuelve False si falló."""
        try:
            self.dispatch(topic, value, headers, partition, offset)
        except Exception:
            return False
        return True

    def dispatch(
        self,
        topic: str,
        value: bytes | None,
        headers: Sequence[tuple[str, bytes]] = (),
        partition: int | None = None,
        offset: int | None = None,
    ) -> None:
        """Entrega el mensaje a su handler y propaga lo que este lance. Un
        mensaje que no se puede leer, o de una empresa inválida, se descarta."""
        try:
            message = json.loads(value) if value is not None else None
        except ValueError:
            message = None
        if not isinstance(message, dict):
            logger.error("kafka_message_discarded", topic=topic, reason="not JSON")
            return

        carrier = _carrier(headers)
        try:
            tenant_id = message_tenant(carrier, message)
        except InvalidTenantError:
            # Retrying never makes it valid, and guessing the tenant is worse
            logger.error("kafka_message_discarded", topic=topic, reason="bad tenant")
            return

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
        with tracer.start_as_current_span(
            f"process {topic}",
            context=extract(carrier),
            kind=trace.SpanKind.CONSUMER,
            attributes=attributes,
        ) as span:
            try:
                if tenant_id is None:
                    self._handlers[topic](message)
                else:
                    context = TenantContext(tenant_id, TenantSource.MESSAGE)
                    with tenant_scope(context):
                        self._handlers[topic](message)
            except Exception as exc:
                kafka_consume_errors.add(1, {"kafka.topic": topic})
                logger.exception("kafka_message_failed", topic=topic)
                span.record_exception(exc)
                span.set_status(trace.StatusCode.ERROR, type(exc).__name__)
                raise
        kafka_messages_consumed.add(1, {"kafka.topic": topic})


def _carrier(headers: Sequence[tuple[str, bytes]]) -> dict[str, str]:
    return {key: raw.decode("utf-8", "replace") for key, raw in headers}


def _tenant_of(carrier: Mapping[str, str], value: bytes | None) -> UUID | None:
    """The message's tenant for its dead letter, when it can be read"""
    try:
        message = json.loads(value) if value is not None else None
        if isinstance(message, dict):
            return message_tenant(carrier, message)
    except ValueError:
        pass
    return None
