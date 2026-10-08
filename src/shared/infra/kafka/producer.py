import asyncio
import json
import threading
from datetime import datetime
from decimal import Decimal

import structlog
from aiokafka import AIOKafkaProducer
from opentelemetry import trace
from opentelemetry.propagate import inject
from opentelemetry.propagators.textmap import Setter

from src.shared.domain.events import DomainEvent
from src.shared.infra.telemetry_instruments import (
    kafka_messages_sent,
    kafka_send_errors,
)

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)


class _KafkaHeaderSetter(Setter[list[tuple[str, bytes]]]):
    def set(self, carrier: list[tuple[str, bytes]], key: str, value: str) -> None:
        carrier.append((key, value.encode("utf-8")))


_header_setter = _KafkaHeaderSetter()


def _inject_trace_context() -> list[tuple[str, bytes]]:
    headers: list[tuple[str, bytes]] = []
    inject(carrier=headers, setter=_header_setter)
    return headers


def _json_serializer(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


class KafkaEventProducer:
    def __init__(self, bootstrap_servers: str) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._producer: AIOKafkaProducer | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._started = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            return

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop,
            args=(self._loop,),
            daemon=True,
            name="kafka-producer",
        )
        self._thread.start()
        self._started.wait(timeout=10)

    def _run_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self._start_producer())
        self._started.set()
        loop.run_forever()

    async def _start_producer(self) -> None:
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap_servers,
            value_serializer=lambda v: json.dumps(v, default=_json_serializer).encode(
                "utf-8"
            ),
        )
        await self._producer.start()
        logger.info(
            "kafka_producer_started",
            bootstrap_servers=self._bootstrap_servers,
        )

    def send(self, topic: str, event: DomainEvent) -> None:
        if self._loop is None or self._producer is None:
            logger.warning("kafka_producer_not_started")
            return

        with tracer.start_as_current_span(
            f"kafka.send.{topic}",
            attributes={"kafka.topic": topic, "event.type": type(event).__name__},
        ):
            headers = _inject_trace_context()
            future = asyncio.run_coroutine_threadsafe(
                self._producer.send_and_wait(topic, event.to_dict(), headers=headers),
                self._loop,
            )
            try:
                future.result(timeout=5)
                kafka_messages_sent.add(1, {"kafka.topic": topic})
                logger.info(
                    "kafka_message_sent",
                    topic=topic,
                    event_type=type(event).__name__,
                    event_id=event.event_id,
                )
            except Exception as e:
                kafka_send_errors.add(1, {"kafka.topic": topic})
                logger.error(
                    "kafka_send_error",
                    topic=topic,
                    event_type=type(event).__name__,
                    error=str(e),
                )

    def send_raw(self, topic: str, data: dict, event_type: str = "unknown") -> None:
        if self._loop is None or self._producer is None:
            logger.warning("kafka_producer_not_started")
            return

        with tracer.start_as_current_span(
            f"kafka.send.{topic}",
            attributes={"kafka.topic": topic, "event.type": event_type},
        ):
            headers = _inject_trace_context()
            future = asyncio.run_coroutine_threadsafe(
                self._producer.send_and_wait(topic, data, headers=headers),
                self._loop,
            )
            try:
                future.result(timeout=5)
                kafka_messages_sent.add(1, {"kafka.topic": topic})
                logger.info(
                    "kafka_message_sent",
                    topic=topic,
                    event_type=event_type,
                    event_id=data.get("event_id"),
                )
            except Exception as e:
                kafka_send_errors.add(1, {"kafka.topic": topic})
                logger.error(
                    "kafka_send_error",
                    topic=topic,
                    event_type=event_type,
                    error=str(e),
                )

    def close(self) -> None:
        if self._loop is None or self._producer is None:
            return

        future = asyncio.run_coroutine_threadsafe(self._producer.stop(), self._loop)
        try:
            future.result(timeout=5)
        except Exception as e:
            logger.error("kafka_producer_close_error", error=str(e))

        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5)

        logger.info("kafka_producer_stopped")
