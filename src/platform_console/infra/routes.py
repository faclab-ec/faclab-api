import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from wireup import Injected

from config import config
from src.auth.domain.exceptions import PlatformConsoleDisabledError
from src.auth.domain.principals import PlatformPrincipal
from src.auth.infra.dependencies import get_platform_principal
from src.data_protection.app.commands.offboarding import (
    CancelOffboardingCommand,
    CancelOffboardingCommandHandler,
    StartOffboardingCommand,
    StartOffboardingCommandHandler,
)
from src.platform_console.app.commands.login import (
    PlatformLoginCommand,
    PlatformLoginCommandHandler,
)
from src.platform_console.app.commands.tenants import (
    ActivateTenantCommand,
    ActivateTenantCommandHandler,
    ChangeTenantSubscriptionCommand,
    ChangeTenantSubscriptionCommandHandler,
    SuspendTenantCommand,
    SuspendTenantCommandHandler,
)
from src.platform_console.app.queries.tenants import (
    GetTenantQuery,
    GetTenantQueryHandler,
    ListTenantsQuery,
    ListTenantsQueryHandler,
)
from src.platform_console.infra.console import PlatformConsole
from src.platform_console.infra.validators import (
    ChangeSubscriptionRequest,
    CreatedTenantResponse,
    CreateTenantRequest,
    OffboardingResponse,
    PlatformLoginRequest,
    PlatformTokenResponse,
    SuspendTenantRequest,
    TenantDetailResponse,
    TenantListResponse,
    TenantStatusResponse,
)
from src.shared.infra.dependencies import get_meta
from src.shared.infra.validators import (
    RESPONSES_COMMAND,
    RESPONSES_QUERY,
    DataResponse,
    Meta,
)
from src.subscriptions.app.commands.plans import describe_plan
from src.subscriptions.app.commands.subscriptions import EnsureSubscriptionCommand
from src.subscriptions.app.queries.subscription import (
    GetSubscriptionQuery,
    GetSubscriptionQueryHandler,
)
from src.subscriptions.app.repositories import PlanRepository
from src.subscriptions.infra.validators import PlanResponse, SubscriptionResponse
from src.tenancy.app.commands.provision_tenant import ProvisionTenantCommand


def platform_enabled() -> None:
    """`PLATFORM_CONSOLE_ENABLED=false` turns the whole console off (503)"""
    if not config.PLATFORM_CONSOLE_ENABLED:
        raise PlatformConsoleDisabledError()


class PlatformRouter:
    """The platform console's API (S8.5), under /api/platform: for the operators
    of Faclab, with a `platform` token that has no tenant. Every route but the
    login declares `get_platform_principal`, and runs through
    `PlatformConsole.run`, which checks the operator is still active."""

    def __init__(self):
        self.router = APIRouter(dependencies=[Depends(platform_enabled)])
        self._setup_routes()

    def _setup_routes(self):
        guard = [Depends(get_platform_principal)]
        self.router.post(
            "/auth/login",
            response_model=DataResponse[PlatformTokenResponse],
            summary="Log a platform operator in",
            description=(
                "Username and password of a user that is an active platform "
                "operator. The token has no tenant, lasts "
                "`PLATFORM_TOKEN_TTL_SECONDS` and has no refresh token. It only "
                "works under /api/platform. Same lockout as the companies' login."
            ),
            responses=RESPONSES_COMMAND,
        )(self.login)
        self.router.get(
            "/tenants",
            response_model=DataResponse[TenantListResponse],
            summary="List the companies",
            responses=RESPONSES_QUERY,
            dependencies=guard,
        )(self.list_tenants)
        self.router.post(
            "/tenants",
            response_model=DataResponse[CreatedTenantResponse],
            status_code=201,
            summary="Create a company and its first administrator",
            description=(
                "The CLI's provisioning (idempotent by RUC): the company, its "
                "administrator, the main branch with its emission point, "
                "warehouse and terminal, and the subscription. A new "
                "administrator gets a temporary password, shown once, that they "
                "must change at the first login."
            ),
            responses=RESPONSES_COMMAND,
            dependencies=guard,
        )(self.create_tenant)
        self.router.get(
            "/tenants/{tenant_id}",
            response_model=DataResponse[TenantDetailResponse],
            summary="A company with its plan, usage and invoicing state",
            responses=RESPONSES_QUERY,
            dependencies=guard,
        )(self.get_tenant)
        self.router.post(
            "/tenants/{tenant_id}/suspend",
            response_model=DataResponse[TenantStatusResponse],
            summary="Suspend a company",
            description=(
                "Nobody of the company can log in or refresh, and its sessions "
                "are revoked; access tokens already issued last until they expire "
                "(15 minutes). Audited in the company's log."
            ),
            responses=RESPONSES_COMMAND,
            dependencies=guard,
        )(self.suspend_tenant)
        self.router.post(
            "/tenants/{tenant_id}/activate",
            response_model=DataResponse[TenantStatusResponse],
            summary="Reactivate a suspended company",
            responses=RESPONSES_COMMAND,
            dependencies=guard,
        )(self.activate_tenant)
        self.router.put(
            "/tenants/{tenant_id}/subscription",
            response_model=DataResponse[SubscriptionResponse],
            summary="Change a company's plan or subscription status",
            responses=RESPONSES_COMMAND,
            dependencies=guard,
        )(self.change_subscription)
        self.router.post(
            "/tenants/{tenant_id}/offboarding",
            response_model=DataResponse[OffboardingResponse],
            summary="Start the termination of a company's contract",
            description=(
                "Cancels its subscription (read-only; it still signs in and "
                "exports its data) and starts the grace period "
                "(`OFFBOARDING_GRACE_DAYS`). The end of the tax retention is "
                "calculated from its last sale. The anonymization and the final "
                "purge are not over HTTP: `make offboard-tenant` "
                "(docs/offboarding-runbook.md). Audited in the company's log."
            ),
            responses=RESPONSES_COMMAND,
            dependencies=guard,
        )(self.start_offboarding)
        self.router.delete(
            "/tenants/{tenant_id}/offboarding",
            response_model=DataResponse[OffboardingResponse],
            summary="Take the termination back, while its data is whole",
            responses=RESPONSES_COMMAND,
            dependencies=guard,
        )(self.cancel_offboarding)
        self.router.get(
            "/plans",
            response_model=DataResponse[list[PlanResponse]],
            summary="List the plans",
            responses=RESPONSES_QUERY,
            dependencies=guard,
        )(self.list_plans)

    def login(
        self,
        handler: Injected[PlatformLoginCommandHandler],
        credentials: PlatformLoginRequest,
        request: Request,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[PlatformTokenResponse]:
        result = handler.handle(
            PlatformLoginCommand(
                username=credentials.username,
                password=credentials.password,
                ip_address=request.client.host if request.client else None,
            )
        )
        return DataResponse(
            data=PlatformTokenResponse(
                access_token=result.token.access_token,
                expires_in=result.token.expires_in,
                token_type=result.token.token_type,
                username=result.username,
                display_name=result.display_name,
            ),
            meta=meta,
        )

    def list_tenants(
        self,
        console: Injected[PlatformConsole],
        operator: PlatformPrincipal = Depends(get_platform_principal),
        q: str | None = Query(None, description="RUC or name contains it"),
        status: str | None = Query(None, pattern="^(active|suspended)$"),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[TenantListResponse]:
        result = console.run(
            operator,
            lambda scope: scope.get(ListTenantsQueryHandler).handle(
                ListTenantsQuery(q=q, status=status, limit=limit, offset=offset)
            ),
        )
        return DataResponse(data=TenantListResponse.model_validate(result), meta=meta)

    def create_tenant(
        self,
        console: Injected[PlatformConsole],
        body: CreateTenantRequest,
        operator: PlatformPrincipal = Depends(get_platform_principal),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[CreatedTenantResponse]:
        password = secrets.token_urlsafe(12)
        result = console.provision_tenant(
            operator,
            ProvisionTenantCommand(
                ruc=body.ruc,
                legal_name=body.legal_name,
                trade_name=body.trade_name,
                admin_username=body.admin_username,
                admin_email=body.admin_email,
                admin_password=password,
                admin_full_name=body.admin_full_name,
            ),
            branch_address=body.branch_address,
            subscription=EnsureSubscriptionCommand(
                plan_code=body.plan_code, trial_days=body.trial_days
            ),
        )
        return DataResponse(
            data=CreatedTenantResponse(
                tenant_id=result["tenant_id"],
                tenant_created=result["tenant_created"],
                user_created=result["user_created"],
                admin_password=password if result["user_created"] else None,
            ),
            meta=meta,
        )

    def get_tenant(
        self,
        tenant_id: UUID,
        console: Injected[PlatformConsole],
        operator: PlatformPrincipal = Depends(get_platform_principal),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[TenantDetailResponse]:
        detail = console.run(
            operator,
            lambda scope: scope.get(GetTenantQueryHandler).handle(
                GetTenantQuery(tenant_id=tenant_id)
            ),
        )
        detail["subscription"] = console.run(
            operator,
            lambda scope: scope.get(GetSubscriptionQueryHandler).handle(
                GetSubscriptionQuery()
            ),
            tenant_id,
        )
        return DataResponse(data=TenantDetailResponse.model_validate(detail), meta=meta)

    def start_offboarding(
        self,
        tenant_id: UUID,
        console: Injected[PlatformConsole],
        operator: PlatformPrincipal = Depends(get_platform_principal),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[OffboardingResponse]:
        result = console.run(
            operator,
            lambda scope: scope.get(StartOffboardingCommandHandler).handle(
                StartOffboardingCommand(
                    grace_days=config.OFFBOARDING_GRACE_DAYS,
                    retention_years=config.TAX_RETENTION_YEARS,
                )
            ),
            tenant_id,
        )
        return DataResponse(data=OffboardingResponse.model_validate(result), meta=meta)

    def cancel_offboarding(
        self,
        tenant_id: UUID,
        console: Injected[PlatformConsole],
        operator: PlatformPrincipal = Depends(get_platform_principal),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[OffboardingResponse]:
        result = console.run(
            operator,
            lambda scope: scope.get(CancelOffboardingCommandHandler).handle(
                CancelOffboardingCommand()
            ),
            tenant_id,
        )
        return DataResponse(data=OffboardingResponse.model_validate(result), meta=meta)

    def suspend_tenant(
        self,
        tenant_id: UUID,
        console: Injected[PlatformConsole],
        body: SuspendTenantRequest | None = None,
        operator: PlatformPrincipal = Depends(get_platform_principal),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[TenantStatusResponse]:
        result = console.run(
            operator,
            lambda scope: scope.get(SuspendTenantCommandHandler).handle(
                SuspendTenantCommand(reason=body.reason if body else None)
            ),
            tenant_id,
        )
        return DataResponse(data=TenantStatusResponse.model_validate(result), meta=meta)

    def activate_tenant(
        self,
        tenant_id: UUID,
        console: Injected[PlatformConsole],
        operator: PlatformPrincipal = Depends(get_platform_principal),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[TenantStatusResponse]:
        result = console.run(
            operator,
            lambda scope: scope.get(ActivateTenantCommandHandler).handle(
                ActivateTenantCommand()
            ),
            tenant_id,
        )
        return DataResponse(data=TenantStatusResponse.model_validate(result), meta=meta)

    def change_subscription(
        self,
        tenant_id: UUID,
        body: ChangeSubscriptionRequest,
        console: Injected[PlatformConsole],
        operator: PlatformPrincipal = Depends(get_platform_principal),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[SubscriptionResponse]:
        def change(scope):
            scope.get(ChangeTenantSubscriptionCommandHandler).handle(
                ChangeTenantSubscriptionCommand(
                    plan_code=body.plan_code,
                    status=body.status,
                    trial_days=body.trial_days,
                )
            )
            return scope.get(GetSubscriptionQueryHandler).handle(GetSubscriptionQuery())

        result = console.run(operator, change, tenant_id)
        return DataResponse(data=SubscriptionResponse.model_validate(result), meta=meta)

    def list_plans(
        self,
        console: Injected[PlatformConsole],
        operator: PlatformPrincipal = Depends(get_platform_principal),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[list[PlanResponse]]:
        plans = console.run(
            operator,
            lambda scope: [
                describe_plan(plan) for plan in scope.get(PlanRepository).get_all()
            ],
        )
        return DataResponse(
            data=[PlanResponse.model_validate(plan) for plan in plans], meta=meta
        )
