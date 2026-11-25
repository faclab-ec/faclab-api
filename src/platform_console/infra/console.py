"""How the platform console reaches the data of every tenant (S8.5).

A request of the API runs as faclab_app, under row-level security and in its
own tenant. The console has no tenant: each operation opens a transaction as
faclab_worker (BYPASSRLS), the role of the platform's CLI, and, when it acts on
a tenant, runs in that tenant's context with the operator as the actor (so the
audit log of that tenant names who did it). It is the only part of the API that
uses `worker_session_maker` in a request, and only under `/api/platform`.
"""

from collections.abc import Callable
from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy import select
from wireup import injectable

from src.auth.app.repositories import UserRepository
from src.auth.domain.exceptions import PermissionDeniedError
from src.auth.domain.principals import PlatformPrincipal
from src.auth.infra.models import UserModel
from src.platform_console.infra.models import PlatformOperatorModel
from src.shared.app.audit import AuditAction, AuditTrail
from src.shared.domain.tenant import TenantContext, TenantSource
from src.shared.infra.database import worker_session_maker
from src.shared.infra.events.scope import create_sync_scope
from src.subscriptions.app.commands.subscriptions import EnsureSubscriptionCommand
from src.tenancy.app.commands.provision_tenant import ProvisionTenantCommand
from src.tenancy.provision import provision

T = TypeVar("T")


@injectable(lifetime="singleton")
class PlatformConsole:
    def run(
        self,
        operator: PlatformPrincipal,
        action: Callable[[Any], T],
        tenant_id: UUID | None = None,
    ) -> T:
        """Runs `action(scope)` in one faclab_worker transaction, in `tenant_id`
        when given. The operator must still be active: a token lives for
        minutes, a deactivation applies at once"""
        with worker_session_maker()() as session:
            self._ensure_active(session, operator)
            context = (
                TenantContext(
                    tenant_id,
                    TenantSource.TASK,
                    user_id=operator.user_id,
                    user_name=operator.display_name,
                )
                if tenant_id is not None
                else None
            )
            with create_sync_scope(session, tenant=context) as scope:
                result = action(scope)
            session.commit()
        return result

    def ensure_active(self, operator: PlatformPrincipal) -> None:
        with worker_session_maker()() as session:
            self._ensure_active(session, operator)

    def provision_tenant(
        self,
        operator: PlatformPrincipal,
        command: ProvisionTenantCommand,
        *,
        branch_address: str | None = None,
        subscription: EnsureSubscriptionCommand | None = None,
    ) -> dict:
        """The CLI's provisioning (idempotent), then, in the new tenant, the
        admin's obligation to change the temporary password and the audit entry"""
        self.ensure_active(operator)
        result = provision(
            command, branch_address=branch_address, subscription=subscription
        )

        def finish(scope: Any) -> None:
            if result["user_created"]:
                users = scope.get(UserRepository)
                admin = users.get_by_id(result["user_id"])
                if admin is not None:
                    admin.reset_password(admin.password_hash)
                    users.update(admin)
            scope.get(AuditTrail).record(
                AuditAction.TENANT_PROVISIONED,
                None,
                after={
                    "ruc": command.ruc,
                    "legal_name": command.legal_name,
                    "admin_username": command.admin_username,
                    "tenant_created": result["tenant_created"],
                    "user_created": result["user_created"],
                },
            )

        self.run(operator, finish, result["tenant_id"])
        return result

    def _ensure_active(self, session, operator: PlatformPrincipal) -> None:
        active = session.scalar(
            select(PlatformOperatorModel.id)
            .join(UserModel, UserModel.id == PlatformOperatorModel.user_id)
            .where(PlatformOperatorModel.user_id == operator.user_id)
            .where(PlatformOperatorModel.is_active.is_(True))
            .where(UserModel.is_active.is_(True))
        )
        if active is None:
            raise PermissionDeniedError("platform access revoked")
