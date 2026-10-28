"""Mensajes que el consumidor no pudo procesar (tabla `dead_letters`).

`DeadLetterStore` los guarda cuando se agotan los reintentos, como
faclab_worker y fuera de la transacción del handler. Las operaciones de
plataforma (`list_pending`, `reprocess`) las usa el CLI
(`python -m src.background.cli`); un reproceso queda registrado en la fila
(`reprocessed_at`, `reprocessed_by`) y en el log.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session, sessionmaker

from src.shared.infra.kafka.models import DeadLetterModel, DeadLetterStatus

logger = structlog.get_logger(__name__)

# Delivers a message to its topic's handler and raises what the handler raises
Dispatch = Callable[[str, bytes | None, Sequence[tuple[str, bytes]]], None]


@dataclass(frozen=True)
class DeadLetter:
    consumer_group: str
    topic: str
    partition: int
    offset: int
    key: str | None
    tenant_id: UUID | None
    headers: dict[str, str]
    value: str | None
    error: str
    attempts: int


class DeadLetterStore:
    def __init__(self, session_maker: sessionmaker[Session]):
        self._session_maker = session_maker

    def record(self, letter: DeadLetter) -> None:
        """Keeps the message; once per message, also if it comes again"""
        with self._session_maker() as session, session.begin():
            dialect = session.get_bind().dialect.name
            insert = postgresql.insert if dialect == "postgresql" else sqlite.insert
            session.execute(
                insert(DeadLetterModel)
                .values(
                    consumer_group=letter.consumer_group,
                    topic=letter.topic,
                    kafka_partition=letter.partition,
                    kafka_offset=letter.offset,
                    key=letter.key,
                    tenant_id=letter.tenant_id,
                    headers=letter.headers,
                    value=letter.value,
                    error=letter.error[:4000],
                    attempts=letter.attempts,
                    status=DeadLetterStatus.PENDING.value,
                    created_at=datetime.now(),
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        "consumer_group",
                        "topic",
                        "kafka_partition",
                        "kafka_offset",
                    ]
                )
            )


def list_pending(
    session_maker: sessionmaker[Session], limit: int = 100
) -> list[DeadLetterModel]:
    """The messages still waiting to be reprocessed, oldest first"""
    with session_maker() as session:
        letters = session.scalars(
            select(DeadLetterModel)
            .where(DeadLetterModel.status == DeadLetterStatus.PENDING)
            .order_by(DeadLetterModel.id)
            .limit(limit)
        ).all()
        session.expunge_all()
        return list(letters)


def reprocess(
    session_maker: sessionmaker[Session],
    letter_id: int,
    by: str,
    dispatch: Dispatch,
    now: datetime | None = None,
) -> DeadLetterModel | None:
    """Delivers a pending dead letter to its handler again. When it works the
    letter is `reprocessed` (by whom, when); when it fails it stays pending
    with one more attempt and the new error. None if there is no such pending
    letter."""
    with session_maker() as session, session.begin():
        letter = session.scalars(
            select(DeadLetterModel)
            .where(
                DeadLetterModel.id == letter_id,
                DeadLetterModel.status == DeadLetterStatus.PENDING,
            )
            .with_for_update()
        ).first()
        if letter is None:
            return None
        headers = [
            (key, value.encode("utf-8")) for key, value in letter.headers.items()
        ]
        value = letter.value.encode("utf-8") if letter.value is not None else None
        try:
            dispatch(letter.topic, value, headers)
        except Exception as exc:
            letter.attempts += 1
            letter.error = (str(exc) or type(exc).__name__)[:4000]
            logger.warning(
                "dead_letter_reprocess_failed",
                dead_letter_id=letter.id,
                topic=letter.topic,
                attempts=letter.attempts,
                reprocessed_by=by,
                error=letter.error,
            )
        else:
            letter.status = DeadLetterStatus.REPROCESSED
            letter.reprocessed_at = now or datetime.now()
            letter.reprocessed_by = by
            logger.info(
                "dead_letter_reprocessed",
                dead_letter_id=letter.id,
                topic=letter.topic,
                tenant_id=str(letter.tenant_id) if letter.tenant_id else None,
                reprocessed_by=by,
            )
        session.flush()
        session.expunge(letter)
        return letter
