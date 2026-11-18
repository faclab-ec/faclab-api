"""The webhooks' history keeps WEBHOOK_RETENTION_DAYS (S6.4): the worker
deletes older deliveries, whatever their status, and the messages left without
any, every tenant's, as faclab_worker."""

from datetime import datetime, timedelta

import structlog
from sqlalchemy import delete, exists, select
from sqlalchemy.orm import Session, sessionmaker

from src.webhooks.infra.models import WebhookDeliveryModel, WebhookMessageModel

logger = structlog.get_logger(__name__)


def purge_history(session_maker: sessionmaker[Session], before: datetime) -> int:
    """Deletes the deliveries created before `before`; how many"""
    with session_maker() as session:
        deliveries = session.execute(
            delete(WebhookDeliveryModel).where(WebhookDeliveryModel.created_at < before)
        ).rowcount
        has_deliveries = exists(
            select(WebhookDeliveryModel.id).where(
                WebhookDeliveryModel.message_id == WebhookMessageModel.id
            )
        )
        session.execute(
            delete(WebhookMessageModel).where(
                WebhookMessageModel.created_at < before, ~has_deliveries
            )
        )
        session.commit()
    return deliveries or 0


def purge() -> int:
    """The worker's task"""
    from config import config
    from src.shared.infra.database import worker_session_maker

    before = datetime.now() - timedelta(days=config.WEBHOOK_RETENTION_DAYS)
    purged = purge_history(worker_session_maker(), before)
    logger.info("webhook_deliveries_purged", deliveries=purged)
    return purged
