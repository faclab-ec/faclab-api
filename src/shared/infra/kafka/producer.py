import asyncio
import json
import threading
from datetime import datetime
from decimal import Decimal
from typing import Any

import structlog
from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError
from opentelemetry import trace

from src.shared.infra.telemetry_instruments import (
    kafka_messages_sent,
    kafka_send_errors,
)

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)


def json_default(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


class KafkaEventProducer:
    def __init__(self, bootstrap_servers: str, retry_delay: float = 5.0) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._retry_delay = retry_delay
        self._producer: AIOKafkaProducer | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._connect_task: asyncio.Task[None] | None = None
        self._thread: threading.Thread | None = None
        self._started = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            return

        self._loop = asyncio.new_event_loop()
        self._connect_task = self._loop.create_task(self._start_producer())
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
        loop.run_forever()

    async def _start_producer(self) -> None:
        # If Kafka is down, keep retrying: until then `publish` raises and the
        # outbox relay keeps the messages for the next poll
        while True:
            producer = AIOKafkaProducer(
                bootstrap_servers=self._bootstrap_servers,
                value_serializer=lambda v: json.dumps(v, default=json_default).encode(
                    "utf-8"
                ),
            )
            try:
                await producer.start()
                break
            except KafkaError as exc:
                await producer.stop()
                logger.warning(
                    "kafka_producer_start_failed",
                    error=str(exc),
                    retry_in=self._retry_delay,
                )
                await asyncio.sleep(self._retry_delay)

        self._producer = producer
        self._started.set()
        logger.info(
            "kafka_producer_started",
            bootstrap_servers=self._bootstrap_servers,
        )

    def publish(
        self, topic: str, value: dict[str, Any], headers: list[tuple[str, bytes]]
    ) -> None:
        """Send a message and wait for the broker's ack; raise if it fails, so
        the outbox relay keeps the message and retries it."""
        if self._loop is None or self._producer is None:
            raise RuntimeError("Kafka producer is not started")

        with tracer.start_as_current_span(
            f"kafka.send.{topic}", attributes={"kafka.topic": topic}
        ):
            future = asyncio.run_coroutine_threadsafe(
                self._producer.send_and_wait(topic, value, headers=headers),
                self._loop,
            )
            try:
                future.result(timeout=5)
            except Exception:
                kafka_send_errors.add(1, {"kafka.topic": topic})
                raise
            kafka_messages_sent.add(1, {"kafka.topic": topic})
            logger.info(
                "kafka_message_sent", topic=topic, event_id=value.get("event_id")
            )

    def close(self) -> None:
        if self._loop is None:
            return

        if self._connect_task is not None:
            self._loop.call_soon_threadsafe(self._connect_task.cancel)
        if self._producer is not None:
            future = asyncio.run_coroutine_threadsafe(self._producer.stop(), self._loop)
            try:
                future.result(timeout=5)
            except Exception as e:
                logger.error("kafka_producer_close_error", error=str(e))

        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5)

        logger.info("kafka_producer_stopped")
