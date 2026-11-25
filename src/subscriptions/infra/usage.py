"""What a tenant has of each resource its plan limits: a read model over the
tables of organization, tenancy, integrations and webhooks (S8.4)."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from wireup import injectable

from src.auth.infra.models import UserModel
from src.integrations.domain.entities import IntegrationClientStatus
from src.integrations.infra.models import IntegrationClientModel
from src.organization.infra.models import BranchModel, PosTerminalModel
from src.shared.app.plans import PlanResource
from src.shared.domain.tenant import require_tenant
from src.shared.infra.tenant import tenant_criteria
from src.subscriptions.app.repositories import TenantUsage
from src.tenancy.infra.models import MembershipModel
from src.webhooks.infra.models import WebhookEndpointModel


@injectable(lifetime="scoped", as_type=TenantUsage)
class SqlAlchemyTenantUsage(TenantUsage):
    def __init__(self, session: Session):
        self.session = session

    def count(self, resource: PlanResource) -> int:
        statement = {
            PlanResource.BRANCHES: select(func.count(BranchModel.id)).where(
                *tenant_criteria(BranchModel), BranchModel.is_active.is_(True)
            ),
            PlanResource.TERMINALS: select(func.count(PosTerminalModel.id)).where(
                *tenant_criteria(PosTerminalModel),
                PosTerminalModel.is_active.is_(True),
            ),
            # Memberships have no row-level security: filtered by hand
            PlanResource.USERS: select(func.count(MembershipModel.id))
            .join(UserModel, UserModel.id == MembershipModel.user_id)
            .where(
                MembershipModel.tenant_id == require_tenant("counting users").tenant_id,
                MembershipModel.active.is_(True),
                UserModel.is_active.is_(True),
            ),
            PlanResource.INTEGRATION_CLIENTS: select(
                func.count(IntegrationClientModel.id)
            ).where(
                *tenant_criteria(IntegrationClientModel),
                IntegrationClientModel.status == IntegrationClientStatus.ACTIVE.value,
            ),
            PlanResource.WEBHOOK_ENDPOINTS: select(
                func.count(WebhookEndpointModel.id)
            ).where(*tenant_criteria(WebhookEndpointModel)),
        }[resource]
        return self.session.execute(statement).scalar_one()
