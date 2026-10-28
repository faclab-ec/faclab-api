"""Publica en Kafka los mensajes del outbox ya confirmados.

Corre en el proceso worker (`worker.py`) o, con RUN_BACKGROUND, en un hilo del
API. Cada lote toma un advisory lock de la transacción: si hay varios relays
(el API y el worker durante un despliegue, o dos workers) solo uno publica a la
vez, y el orden por empresa se mantiene. Toma los pendientes con FOR UPDATE SKIP
LOCKED y los marca como publicados en la misma transacción.

El orden es por empresa, no global (ADR-0005). La clave de cada mensaje es su
empresa, así que los de una empresa van por la misma partición y en orden. Un
mensaje que falla espera su próximo intento (backoff exponencial) y frena solo a
los siguientes de su empresa. Tras OUTBOX_MAX_ATTEMPTS pasa a `failed` y deja de
frenarlos: queda para reprocesarlo a mano (`python -m src.background.cli`). Si
lo que falla es el broker (`BrokerUnavailableError`), el lote se corta sin
contar el intento: una caída de Kafka no deja mensajes sanos en `failed`.
"""

import threading
import zlib
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

import structlog
from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from src.shared.infra.outbox.models import OutboxMessageModel, OutboxStatus

logger = structlog.get_logger(__name__)

# Key of the advisory lock that lets one relay publish at a time
RELAY_LOCK_KEY = zlib.crc32(b"faclab.outbox_relay")


class BrokerUnavailableError(ConnectionError):
    """The broker can't be reached; nothing is wrong with the message"""


class MessagePublisher(Protocol):
    def publish(
        self,
        topic: str,
        value: dict[str, Any],
        headers: list[tuple[str, bytes]],
        key: str | None = None,
    ) -> None:
        """Send the message and wait for the broker; raise if it fails, with
        `BrokerUnavailableError` when the broker is the problem."""
        ...


class OutboxRelay:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        publisher: MessagePublisher,
        poll_interval: float = 1.0,
        batch_size: int = 100,
        max_attempts: int = 10,
        retry_base_seconds: float = 5.0,
        retry_max_seconds: float = 600.0,
        clock: Callable[[], datetime] = datetime.now,
        on_cycle: Callable[[], None] | None = None,
    ):
        self._session_factory = session_factory
        self._publisher = publisher
        self._poll_interval = poll_interval
        self._batch_size = batch_size
        self._max_attempts = max_attempts
        self._retry_base_seconds = retry_base_seconds
        self._retry_max_seconds = retry_max_seconds
        self._clock = clock
        # Called after each poll that ran without errors (worker health)
        self._on_cycle = on_cycle
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
            except BrokerUnavailableError as exc:
                logger.warning("outbox_broker_unavailable", error=str(exc))
            except Exception:
                logger.exception("outbox_relay_error")
            else:
                if self._on_cycle is not None:
                    self._on_cycle()
            self._wake.wait(timeout=self._poll_interval)

    def publish_pending(self) -> int:
        """Publish one batch of the messages that are due; return how many were
        sent. Raises BrokerUnavailableError, after committing what it sent,
        when the broker stops answering."""
        published = 0
        with self._session_factory() as session:
            if not _take_relay_lock(session):
                return 0
            now = self._clock()
            # Tenants holding a message until its next attempt
            blocked: set[UUID] = set(session.scalars(_waiting_tenants(now)))
            messages = session.scalars(
                select(OutboxMessageModel)
                .where(
                    OutboxMessageModel.status == OutboxStatus.PENDING,
                    or_(
                        OutboxMessageModel.next_attempt_at.is_(None),
                        OutboxMessageModel.next_attempt_at <= now,
                    ),
                    OutboxMessageModel.tenant_id.not_in(_waiting_tenants(now)),
                )
                .order_by(OutboxMessageModel.id)
                .with_for_update(skip_locked=True)
                .limit(self._batch_size)
            ).all()
            broker_error: BrokerUnavailableError | None = None
            for message in messages:
                if message.tenant_id in blocked:
                    continue
                try:
                    self._publisher.publish(
                        message.topic,
                        message.payload,
                        [(k, v.encode("utf-8")) for k, v in message.headers.items()],
                        key=str(message.tenant_id),
                    )
                except BrokerUnavailableError as exc:
                    broker_error = exc
                    break
                except Exception as exc:
                    if self._record_failure(message, exc, now):
                        blocked.add(message.tenant_id)
                    continue
                message.status = OutboxStatus.PUBLISHED
                message.published_at = self._clock()
                message.next_attempt_at = None
                published += 1
            session.commit()
        if broker_error is not None:
            raise broker_error
        return published

    def _record_failure(
        self, message: OutboxMessageModel, exc: Exception, now: datetime
    ) -> bool:
        """Count the attempt; True while the message keeps waiting (and holds
        its tenant back), False once it is failed."""
        message.attempts += 1
        message.last_error = str(exc)[:1000]
        if message.attempts >= self._max_attempts:
            message.status = OutboxStatus.FAILED
            message.next_attempt_at = None
            logger.error(
                "outbox_message_failed",
                hint=(
                    f"Could not publish {message.event_type} to {message.topic} "
                    f"after {message.attempts} attempts; it is failed. Retry it "
                    f"with `python -m src.background.cli outbox-retry {message.id}`"
                ),
                outbox_id=message.id,
                event_id=message.event_id,
                topic=message.topic,
                attempts=message.attempts,
                error=message.last_error,
            )
            return False
        delay = min(
            self._retry_base_seconds * 2 ** (message.attempts - 1),
            self._retry_max_seconds,
        )
        message.next_attempt_at = now + timedelta(seconds=delay)
        logger.warning(
            "outbox_publish_failed",
            outbox_id=message.id,
            event_id=message.event_id,
            topic=message.topic,
            attempts=message.attempts,
            retry_in=delay,
            error=message.last_error,
        )
        return True


def _waiting_tenants(now: datetime):
    return select(OutboxMessageModel.tenant_id).where(
        OutboxMessageModel.status == OutboxStatus.PENDING,
        OutboxMessageModel.next_attempt_at > now,
    )


def _take_relay_lock(session: Session) -> bool:
    """One relay at a time; the lock goes with the batch's transaction"""
    if session.get_bind().dialect.name != "postgresql":
        return True
    return bool(
        session.scalar(
            text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": RELAY_LOCK_KEY}
        )
    )


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
