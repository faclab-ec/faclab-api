from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from src.subscriptions.domain.entities import SubscriptionStatus
from src.subscriptions.infra.validators import SubscriptionResponse


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, from_attributes=True
    )


class PlatformLoginRequest(CamelModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class PlatformTokenResponse(CamelModel):
    access_token: str
    expires_in: int
    token_type: str = "Bearer"
    username: str
    display_name: str


class PlanRefResponse(CamelModel):
    code: str
    name: str


class TenantSummaryResponse(CamelModel):
    id: UUID
    ruc: str
    legal_name: str
    trade_name: str | None = None
    status: str
    created_at: datetime | None = None
    subscription_status: str | None = None
    trial_ends_at: datetime | None = None
    plan: PlanRefResponse | None = None
    active_users: int
    active_branches: int


class TenantInvoicingResponse(CamelModel):
    pending_invoices: int
    rejected_invoices: int
    authorized_invoices: int
    uninvoiced_sales: int
    open_discrepancies: int
    documents_this_month: int


class TenantDetailResponse(TenantSummaryResponse):
    invoicing: TenantInvoicingResponse
    subscription: SubscriptionResponse | None = None


class TenantListResponse(CamelModel):
    items: list[TenantSummaryResponse]
    total: int
    limit: int
    offset: int


class CreateTenantRequest(CamelModel):
    ruc: str = Field(min_length=13, max_length=13)
    legal_name: str = Field(min_length=1, max_length=300)
    trade_name: str | None = Field(default=None, max_length=300)
    admin_username: str = Field(min_length=3, max_length=64)
    admin_email: str = Field(min_length=3, max_length=128)
    admin_full_name: str | None = Field(default=None, max_length=64)
    branch_address: str | None = Field(default=None, max_length=300)
    plan_code: str | None = Field(default=None, max_length=40)
    trial_days: int | None = Field(default=None, ge=1, le=365)


class CreatedTenantResponse(CamelModel):
    tenant_id: UUID
    tenant_created: bool
    user_created: bool
    # The temporary password of a new admin: shown only here, it must be
    # changed at the first login. None when the user already existed
    admin_password: str | None = None


class SuspendTenantRequest(CamelModel):
    reason: str | None = Field(default=None, max_length=300)


class TenantStatusResponse(CamelModel):
    status: str
    revoked_sessions: int | None = None


class OffboardingResponse(CamelModel):
    """The dates of a company's offboarding (S8.7)"""

    status: str
    offboarding_started_at: datetime | None = None
    grace_ends_at: datetime | None = Field(
        None, description="From here its data can be anonymized"
    )
    retention_ends_at: datetime | None = Field(
        None, description="From here everything of it can be deleted"
    )
    anonymized_at: datetime | None = None


class ChangeSubscriptionRequest(CamelModel):
    plan_code: str | None = Field(default=None, max_length=40)
    status: SubscriptionStatus | None = None
    trial_days: int | None = Field(default=None, ge=1, le=365)
