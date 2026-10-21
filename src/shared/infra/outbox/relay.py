"""Publica en Kafka los mensajes del outbox ya confirmados.

Corre en un hilo del proceso de la API (lo arranca el lifespan cuando
KAFKA_ENABLED). Toma los pendientes con FOR UPDATE SKIP LOCKED, así varias
réplicas no publican el mismo mensaje, y los marca como publicados en la misma
transacción. Si Kafka falla, se detiene en ese mensaje para no alterar el orden
y lo reintenta en la siguiente vuelta. La clave de cada mensaje es su empresa:
los de una empresa van por la misma partición, en orden.
"""

import threading
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

import structlog
from sqlalchemy.orm import Session

from src.shared.infra.outbox.models import OutboxMessageModel

logger = structlog.get_logger(__name__)


class MessagePublisher(Protocol):
    def publish(
        self,
        topic: str,
        value: dict[str, Any],
        headers: list[tuple[str, bytes]],
        key: str | None = None,
    ) -> None:
        """Send the message and wait for the broker; raise if it fails."""
        ...


class OutboxRelay:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        publisher: MessagePublisher,
        poll_interval: float = 5.0,
        batch_size: int = 100,
    ):
        self._session_factory = session_factory
        self._publisher = publisher
        self._poll_interval = poll_interval
        self._batch_size = batch_size
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="outbox-relay"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    def wake(self) -> None:
        """Publish now instead of waiting for the next poll"""
        self._wake.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.clear()
            try:
                while self.publish_pending() == self._batch_size:
                    pass
            except Exception:
                logger.exception("outbox_relay_error")
            self._wake.wait(timeout=self._poll_interval)

    def publish_pending(self) -> int:
        """Publish one batch of pending messages; return how many were sent."""
        published = 0
        with self._session_factory() as session:
            messages = (
                session.query(OutboxMessageModel)
                .filter(OutboxMessageModel.published_at.is_(None))
                .order_by(OutboxMessageModel.id)
                .with_for_update(skip_locked=True)
                .limit(self._batch_size)
                .all()
            )
            for message in messages:
                try:
                    self._publisher.publish(
                        message.topic,
                        message.payload,
                        [(k, v.encode("utf-8")) for k, v in message.headers.items()],
                        key=str(message.tenant_id),
                    )
                except Exception as exc:
                    message.attempts += 1
                    message.last_error = str(exc)[:1000]
                    logger.warning(
                        "outbox_publish_failed",
                        event_id=message.event_id,
                        topic=message.topic,
                        attempts=message.attempts,
                        error=str(exc),
                    )
                    break
                message.published_at = datetime.now()
                published += 1
            session.commit()
        return published


_relay: OutboxRelay | None = None


def start(relay: OutboxRelay) -> None:
    global _relay
    _relay = relay
    relay.start()


def stop() -> None:
    global _relay
    if _relay is not None:
        _relay.stop()
        _relay = None


def wake() -> None:
    if _relay is not None:
        _relay.wake()
