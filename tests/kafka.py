"""A KafkaEventProducer whose event loop runs in a thread, as after start(),
with a fake broker instead of Kafka: what the relay sends goes through the
real producer (its `send` span, its headers) and stays in memory."""

import asyncio
import threading
from collections.abc import Generator
from contextlib import contextmanager

from src.shared.infra.kafka.producer import KafkaEventProducer


class FakeBroker:
    def __init__(self):
        self.sent: list[tuple[str, dict, list[tuple[str, bytes]]]] = []
        self.keys: list[bytes | None] = []

    async def send_and_wait(self, topic, value, key=None, headers=None):
        self.sent.append((topic, value, headers or []))
        self.keys.append(key)


@contextmanager
def fake_producer() -> Generator[tuple[KafkaEventProducer, FakeBroker]]:
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    broker = FakeBroker()
    producer = KafkaEventProducer("localhost:9092")
    producer._loop = loop
    producer._producer = broker  # ty: ignore[invalid-assignment]
    try:
        yield producer, broker
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)
        loop.close()
