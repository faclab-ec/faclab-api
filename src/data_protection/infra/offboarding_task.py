"""Anonymizes the companies whose grace period ended (S8.7), in the worker, only
with `OFFBOARDING_AUTO_ANONYMIZE`. The final purge never runs by itself.

A company with messages still on their way to other services is skipped and
tried again on the next pass; anything else that fails is logged and doesn't
stop the others. Idempotent: an anonymized company is no longer due.
"""

from datetime import datetime

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from src.data_protection.app.commands.offboarding import (
    AnonymizeTenantCommand,
    AnonymizeTenantCommandHandler,
)
from src.data_protection.domain.exceptions import PendingMessagesError
from src.shared.domain.tenant import TenantContext, TenantSource
from src.shared.infra.events.scope import create_sync_scope
from src.tenancy.infra.models import TenantModel

logger = structlog.get_logger(__name__)


def due_tenants(session_maker: sessionmaker[Session], now: datetime) -> list:
    with session_maker() as session:
        return list(
            session.execute(
                select(TenantModel.id, TenantModel.ruc)
                .where(TenantModel.offboarding_started_at.is_not(None))
                .where(TenantModel.anonymized_at.is_(None))
                .where(TenantModel.grace_ends_at <= now)
                .order_by(TenantModel.grace_ends_at)
            ).all()
        )


def anonymize_due(
    session_maker: sessionmaker[Session] | None = None, now: datetime | None = None
) -> int:
    """The worker's task: returns how many companies it anonymized"""
    from config import config
    from src.shared.infra.database import worker_session_maker

    if not config.OFFBOARDING_AUTO_ANONYMIZE:
        return 0
    session_maker = session_maker or worker_session_maker()
    now = now or datetime.now()
    done = 0
    for tenant_id, ruc in due_tenants(session_maker, now):
        context = TenantContext(tenant_id, TenantSource.TASK, user_name="worker")
        try:
            with session_maker() as session:
                with create_sync_scope(session, tenant=context) as scope:
                    scope.get(AnonymizeTenantCommandHandler).handle(
                        AnonymizeTenantCommand(now=now)
                    )
                session.commit()
            done += 1
        except PendingMessagesError:
            logger.warning("tenant_anonymization_waits", ruc=ruc)
        except Exception as exc:
            logger.error(
                "tenant_anonymization_failed", ruc=ruc, error_type=type(exc).__name__
            )
    return done
