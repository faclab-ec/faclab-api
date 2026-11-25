"""What the platform does to a tenant (S8.5). The handlers run in the tenant's
context, opened by the console with the operator as actor, so each entry goes
to the tenant's own audit log."""

from dataclasses import dataclass
from datetime import datetime

import structlog
from wireup import injectable

from src.auth.app.repositories import AuthSessionRepository
from src.platform_console.domain.exceptions import (
    TenantAlreadySuspendedError,
    TenantNotSuspendedError,
)
from src.shared.app.audit import AuditAction, AuditTrail
from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.tenant import require_tenant
from src.subscriptions.app.commands.subscriptions import (
    ChangeSubscriptionCommand,
    ChangeSubscriptionCommandHandler,
)
from src.subscriptions.domain.entities import SubscriptionStatus
from src.tenancy.app.repositories import TenantRepository
from src.tenancy.domain.exceptions import TenantNotFoundError

logger = structlog.get_logger(__name__)


def _operator() -> str:
    return require_tenant("a platform operation").user_name or "platform"


@dataclass
class SuspendTenantCommand(Command):
    reason: str | None = None


@injectable(lifetime="scoped")
class SuspendTenantCommandHandler(CommandHandler[SuspendTenantCommand, dict]):
    """Suspends the context tenant: nobody can log in or refresh, and its open
    sessions are revoked, so the access tokens already issued are the only
    thing left, for at most their lifetime (15 minutes)"""

    def __init__(
        self,
        tenants: TenantRepository,
        sessions: AuthSessionRepository,
        audit: AuditTrail,
    ):
        self.tenants = tenants
        self.sessions = sessions
        self.audit = audit

    def _handle(self, command: SuspendTenantCommand) -> dict:
        tenant = self.tenants.get(require_tenant().tenant_id)
        if tenant is None:
            raise TenantNotFoundError()
        if not tenant.is_active:
            raise TenantAlreadySuspendedError()
        tenant.suspend()
        self.tenants.update(tenant)
        revoked = self.sessions.revoke_all_for_tenant(tenant.id, datetime.now())
        self.audit.record(
            AuditAction.TENANT_SUSPENDED,
            None,
            before={"status": "active"},
            after={
                "status": "suspended",
                "ruc": tenant.ruc,
                "reason": (command.reason or "").strip() or None,
                "revoked_sessions": revoked,
            },
        )
        logger.info(
            "tenant_suspended",
            ruc=tenant.ruc,
            by=_operator(),
            revoked_sessions=revoked,
        )
        return {"status": tenant.status.value, "revoked_sessions": revoked}


@dataclass
class ActivateTenantCommand(Command):
    pass


@injectable(lifetime="scoped")
class ActivateTenantCommandHandler(CommandHandler[ActivateTenantCommand, dict]):
    def __init__(self, tenants: TenantRepository, audit: AuditTrail):
        self.tenants = tenants
        self.audit = audit

    def _handle(self, command: ActivateTenantCommand) -> dict:
        tenant = self.tenants.get(require_tenant().tenant_id)
        if tenant is None:
            raise TenantNotFoundError()
        if tenant.is_active:
            raise TenantNotSuspendedError()
        tenant.activate()
        self.tenants.update(tenant)
        self.audit.record(
            AuditAction.TENANT_ACTIVATED,
            None,
            before={"status": "suspended"},
            after={"status": "active", "ruc": tenant.ruc},
        )
        logger.info("tenant_activated", ruc=tenant.ruc, by=_operator())
        return {"status": tenant.status.value}


@dataclass
class ChangeTenantSubscriptionCommand(Command):
    plan_code: str | None = None
    status: SubscriptionStatus | None = None
    trial_days: int | None = None


@injectable(lifetime="scoped")
class ChangeTenantSubscriptionCommandHandler(
    CommandHandler[ChangeTenantSubscriptionCommand, dict]
):
    """The platform's change of a plan or status (S8.4's command), audited"""

    def __init__(self, change: ChangeSubscriptionCommandHandler, audit: AuditTrail):
        self.change = change
        self.audit = audit

    def _handle(self, command: ChangeTenantSubscriptionCommand) -> dict:
        result = self.change.handle(
            ChangeSubscriptionCommand(
                by=_operator(),
                plan_code=command.plan_code,
                status=command.status,
                trial_days=command.trial_days,
            )
        )
        self.audit.record(
            AuditAction.SUBSCRIPTION_CHANGED,
            None,
            after={
                "plan": result["plan_code"],
                "status": result["status"],
                "trial_ends_at": result["trial_ends_at"],
            },
        )
        return result
