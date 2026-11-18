"""The notice that an endpoint was disabled after sustained failures (S6.4):
an email to every active administrator of the company, through the platform's
mailer. Best effort: without email (EMAIL_ENABLED=false) or if the server
fails, the log keeps it and the endpoint shows `disabledReason: failing`."""

from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from src.auth.domain.entities import Role
from src.auth.infra.models import UserModel
from src.shared.app.mail import Mailer, OutgoingMail
from src.tenancy.infra.models import MembershipModel, TenantModel
from src.webhooks.app.views import redacted_url

logger = structlog.get_logger(__name__)

SUBJECT = "Faclab desactivó un endpoint de webhooks"


def admin_emails(session: Session, tenant_id: UUID) -> list[str]:
    """The active administrators of the company, across tenants (faclab_worker)"""
    return list(
        session.scalars(
            select(UserModel.email)
            .join(MembershipModel, MembershipModel.user_id == UserModel.id)
            .where(
                MembershipModel.tenant_id == tenant_id,
                MembershipModel.role == Role.ADMIN.value,
                MembershipModel.active.is_(True),
                UserModel.is_active.is_(True),
            )
            .order_by(UserModel.id)
        )
    )


def notice(endpoint: dict) -> str:
    return (
        f"El endpoint de webhooks {redacted_url(endpoint['url'])} (id "
        f"{endpoint['id']}) no respondió bien a ninguna entrega durante unos tres "
        "días y Faclab lo desactivó.\n\n"
        "Lo que tenía pendiente se conserva y no se envía mientras esté "
        "desactivado. Revisa el sistema que recibe los webhooks, actívalo de nuevo "
        "en Faclab (o con POST /api/v1/webhook-endpoints/{id}/enable) y reenvía las "
        "entregas fallidas desde su historial.\n"
    )


class DisabledEndpointNotifier:
    def __init__(self, session_maker: sessionmaker[Session], mailer: Mailer):
        self.session_maker = session_maker
        self.mailer = mailer

    def __call__(self, tenant_id: UUID, endpoint: dict) -> int:
        """How many administrators were told"""
        try:
            with self.session_maker() as session:
                recipients = admin_emails(session, tenant_id)
                company = session.scalar(
                    select(TenantModel.legal_name).where(TenantModel.id == tenant_id)
                )
        except Exception:
            logger.exception("webhook_disabled_notice_failed", tenant_id=str(tenant_id))
            return 0
        sent = 0
        for recipient in recipients:
            try:
                self.mailer.send(
                    OutgoingMail(
                        to=recipient,
                        subject=SUBJECT,
                        text=notice(endpoint),
                        sender_name=company,
                    )
                )
                sent += 1
            except Exception as exc:
                logger.warning(
                    "webhook_disabled_notice_not_sent",
                    tenant_id=str(tenant_id),
                    endpoint_id=endpoint["id"],
                    error_code=getattr(exc, "error_code", type(exc).__name__),
                )
        return sent
