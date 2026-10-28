"""Deletes the outbox messages published before OUTBOX_RETENTION_DAYS, of every
tenant (as faclab_worker). Until then they stay to look at or send again; the
failed and pending ones are never purged. The worker runs it periodically."""

from datetime import datetime, timedelta

import structlog
from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from src.shared.infra.outbox.models import OutboxMessageModel, OutboxStatus

logger = structlog.get_logger(__name__)


def purge_published(session_maker: sessionmaker[Session], before: datetime) -> int:
    """Deletes the messages published before `before`; returns how many"""
    with session_maker() as session, session.begin():
        result = session.execute(
            delete(OutboxMessageModel)
            .where(
                OutboxMessageModel.status == OutboxStatus.PUBLISHED,
                OutboxMessageModel.published_at < before,
            )
            .execution_options(synchronize_session=False)
        )
        return result.rowcount


def purge() -> int:
    """The worker's task: purges with the configured retention"""
    from config import config
    from src.shared.infra.database import worker_session_maker

    retention = timedelta(days=config.OUTBOX_RETENTION_DAYS)
    deleted = purge_published(worker_session_maker(), datetime.now() - retention)
    logger.info(
        "outbox_messages_purged",
        deleted=deleted,
        retention_days=config.OUTBOX_RETENTION_DAYS,
    )
    return deleted
