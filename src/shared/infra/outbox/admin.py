"""Platform operations on the outbox: list the failed messages and put them
back in the queue. They run as faclab_worker over every tenant, from the CLI
(`python -m src.background.cli`); the HTTP console arrives with the platform
role (S8.5). A retry is recorded on the message (`retried_at`, `retried_by`)
and in the log."""

from collections.abc import Sequence
from datetime import datetime

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from src.shared.infra.outbox.models import OutboxMessageModel, OutboxStatus

logger = structlog.get_logger(__name__)


def list_failed(
    session_maker: sessionmaker[Session], limit: int = 100
) -> list[OutboxMessageModel]:
    """The failed messages, oldest first"""
    with session_maker() as session:
        messages = session.scalars(
            select(OutboxMessageModel)
            .where(OutboxMessageModel.status == OutboxStatus.FAILED)
            .order_by(OutboxMessageModel.id)
            .limit(limit)
        ).all()
        session.expunge_all()
        return list(messages)


def retry_failed(
    session_maker: sessionmaker[Session],
    ids: Sequence[int] | None,
    by: str,
    now: datetime | None = None,
) -> list[int]:
    """Puts the failed messages back as pending, with their attempts from zero;
    every failed one when `ids` is None. Returns the ids it changed: a message
    that isn't failed is left as it is."""
    now = now or datetime.now()
    with session_maker() as session, session.begin():
        query = (
            select(OutboxMessageModel)
            .where(OutboxMessageModel.status == OutboxStatus.FAILED)
            .order_by(OutboxMessageModel.id)
            .with_for_update()
        )
        if ids is not None:
            query = query.where(OutboxMessageModel.id.in_(ids))
        retried = []
        for message in session.scalars(query):
            message.status = OutboxStatus.PENDING
            message.attempts = 0
            message.next_attempt_at = None
            message.retried_at = now
            message.retried_by = by
            retried.append(message.id)
            logger.info(
                "outbox_message_retried",
                outbox_id=message.id,
                event_id=message.event_id,
                topic=message.topic,
                tenant_id=str(message.tenant_id),
                retried_by=by,
            )
        return retried
