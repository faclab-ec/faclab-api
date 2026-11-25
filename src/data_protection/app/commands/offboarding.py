"""The steps of a company's offboarding (S8.7). They run in the tenant's context
with the platform operator as the actor (the console and the CLI open it), so
each entry goes to the tenant's own audit log."""

import calendar
from dataclasses import dataclass
from datetime import datetime, timedelta

import structlog
from wireup import injectable

from src.auth.app.repositories import AuthSessionRepository
from src.data_protection.app.offboarding import TenantDataCleaner
from src.data_protection.domain.exceptions import (
    GraceNotEndedError,
    OffboardingStepError,
    PendingMessagesError,
    RetentionNotEndedError,
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
from src.tenancy.domain.entities import Tenant
from src.tenancy.domain.exceptions import TenantNotFoundError

logger = structlog.get_logger(__name__)


def add_years(moment: datetime, years: int) -> datetime:
    """The same day `years` later (29 February becomes 28)"""
    year = moment.year + years
    day = min(moment.day, calendar.monthrange(year, moment.month)[1])
    return moment.replace(year=year, day=day)


def _operator() -> str:
    return require_tenant("an offboarding step").user_name or "platform"


def _tenant(tenants: TenantRepository) -> Tenant:
    tenant = tenants.get(require_tenant().tenant_id)
    if tenant is None:
        raise TenantNotFoundError()
    return tenant


def _dates(tenant: Tenant) -> dict:
    return {
        "offboarding_started_at": tenant.offboarding_started_at,
        "grace_ends_at": tenant.grace_ends_at,
        "retention_ends_at": tenant.retention_ends_at,
        "anonymized_at": tenant.anonymized_at,
    }


def _view(tenant: Tenant) -> dict:
    return {"status": tenant.status.value, **_dates(tenant)}


@dataclass
class StartOffboardingCommand(Command):
    grace_days: int
    retention_years: int
    now: datetime | None = None


@injectable(lifetime="scoped")
class StartOffboardingCommandHandler(CommandHandler[StartOffboardingCommand, dict]):
    """The company is cancelled: read-only (it still exports and signs in)
    until the grace period ends. The tax retention counts from its last sale"""

    def __init__(
        self,
        tenants: TenantRepository,
        cleaner: TenantDataCleaner,
        subscription: ChangeSubscriptionCommandHandler,
        audit: AuditTrail,
    ):
        self.tenants = tenants
        self.cleaner = cleaner
        self.subscription = subscription
        self.audit = audit

    def _handle(self, command: StartOffboardingCommand) -> dict:
        now = command.now or datetime.now()
        tenant = _tenant(self.tenants)
        last_sale = self.cleaner.last_fiscal_activity(tenant.id) or now
        tenant.start_offboarding(
            now,
            grace_ends_at=now + timedelta(days=command.grace_days),
            retention_ends_at=add_years(last_sale, command.retention_years),
        )
        self.tenants.update(tenant)
        self.subscription.handle(
            ChangeSubscriptionCommand(
                by=_operator(), status=SubscriptionStatus.CANCELLED
            )
        )
        self.audit.record(
            AuditAction.TENANT_OFFBOARDING_STARTED,
            None,
            after={"ruc": tenant.ruc, **_dates(tenant)},
        )
        logger.info("tenant_offboarding_started", ruc=tenant.ruc, by=_operator())
        return _view(tenant)


@dataclass
class CancelOffboardingCommand(Command):
    pass


@injectable(lifetime="scoped")
class CancelOffboardingCommandHandler(CommandHandler[CancelOffboardingCommand, dict]):
    """The way back, while the data is whole: the grace period or after it but
    before anonymizing"""

    def __init__(
        self,
        tenants: TenantRepository,
        subscription: ChangeSubscriptionCommandHandler,
        audit: AuditTrail,
    ):
        self.tenants = tenants
        self.subscription = subscription
        self.audit = audit

    def _handle(self, command: CancelOffboardingCommand) -> dict:
        tenant = _tenant(self.tenants)
        before = _dates(tenant)
        tenant.cancel_offboarding()
        self.tenants.update(tenant)
        self.subscription.handle(
            ChangeSubscriptionCommand(by=_operator(), status=SubscriptionStatus.ACTIVE)
        )
        self.audit.record(
            AuditAction.TENANT_OFFBOARDING_CANCELLED,
            None,
            before={"ruc": tenant.ruc, **before},
            after={"ruc": tenant.ruc, **_dates(tenant)},
        )
        logger.info("tenant_offboarding_cancelled", ruc=tenant.ruc, by=_operator())
        return _view(tenant)


@dataclass
class AnonymizeTenantCommand(Command):
    # Only for a test company that must not wait for its grace period
    skip_grace: bool = False
    now: datetime | None = None


@injectable(lifetime="scoped")
class AnonymizeTenantCommandHandler(CommandHandler[AnonymizeTenantCommand, dict]):
    """Step 2: deletes what tax law doesn't need and anonymizes the personal
    data of what it does. Nobody can sign in afterwards."""

    def __init__(
        self,
        tenants: TenantRepository,
        cleaner: TenantDataCleaner,
        sessions: AuthSessionRepository,
        audit: AuditTrail,
    ):
        self.tenants = tenants
        self.cleaner = cleaner
        self.sessions = sessions
        self.audit = audit

    def _handle(self, command: AnonymizeTenantCommand) -> dict:
        now = command.now or datetime.now()
        tenant = _tenant(self.tenants)
        if not tenant.in_offboarding or tenant.grace_ends_at is None:
            raise OffboardingStepError("Start the offboarding first")
        if tenant.anonymized_at is not None:
            raise OffboardingStepError("The company is already anonymized")
        if tenant.grace_ends_at > now and not command.skip_grace:
            raise GraceNotEndedError(tenant.grace_ends_at)
        pending = self.cleaner.pending_outbox(tenant.id)
        if pending:
            raise PendingMessagesError(pending)
        # Before the data goes: the entry is the platform's, it stays as it is
        self.audit.record(
            AuditAction.TENANT_ANONYMIZED,
            None,
            after={"ruc": tenant.ruc, "skip_grace": command.skip_grace},
        )
        result = self.cleaner.anonymize(tenant.id)
        self.sessions.revoke_all_for_tenant(tenant.id, now)
        tenant.mark_anonymized(now)
        self.tenants.update(tenant)
        logger.info(
            "tenant_anonymized",
            ruc=tenant.ruc,
            by=_operator(),
            deleted=sum(result["purge"].values()),
            anonymized=sum(result["anonymize"].values()),
        )
        return {**_view(tenant), **result}


@dataclass
class PurgeTenantCommand(Command):
    confirm_ruc: str
    now: datetime | None = None


@injectable(lifetime="scoped")
class PurgeTenantCommandHandler(CommandHandler[PurgeTenantCommand, dict]):
    """Step 3: nothing of the company stays. Only once the tax retention has
    ended and with its RUC typed again; it can't be undone"""

    def __init__(self, tenants: TenantRepository, cleaner: TenantDataCleaner):
        self.tenants = tenants
        self.cleaner = cleaner

    def _handle(self, command: PurgeTenantCommand) -> dict:
        now = command.now or datetime.now()
        tenant = _tenant(self.tenants)
        if tenant.anonymized_at is None or tenant.retention_ends_at is None:
            raise OffboardingStepError("Anonymize the company first")
        if command.confirm_ruc.strip() != tenant.ruc:
            raise OffboardingStepError("The RUC typed is not the company's")
        if tenant.retention_ends_at > now:
            raise RetentionNotEndedError(tenant.retention_ends_at)
        ruc = tenant.ruc
        deleted = self.cleaner.purge(tenant.id)
        # Its audit log went with it: this line is the only trace
        logger.warning(
            "tenant_purged", ruc=ruc, by=_operator(), rows=sum(deleted.values())
        )
        return {"purged": True, "deleted": deleted}
