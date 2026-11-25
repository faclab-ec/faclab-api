from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from src.shared.app.plans import PlanResource
from src.subscriptions.domain.entities import SubscriptionStatus

_CONFIG = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class PlanResponse(BaseModel):
    model_config = _CONFIG

    code: str = Field(description="Plan code")
    name: str = Field(description="Plan name")
    public_api: bool = Field(description="Whether it includes the public API (/api/v1)")
    max_branches: int | None = Field(
        None, description="Active branches; null: no limit"
    )
    max_terminals: int | None = Field(None, description="Active POS terminals")
    max_users: int | None = Field(None, description="Active users of the company")
    max_integration_clients: int | None = Field(
        None, description="Integration clients not revoked"
    )
    max_webhook_endpoints: int | None = Field(None, description="Webhook endpoints")
    max_monthly_documents: int | None = Field(
        None,
        description="Electronic documents a month (invoices and credit notes). A soft "
        "limit: the invoicing of sales already made never stops",
    )


class ResourceUsageResponse(BaseModel):
    model_config = _CONFIG

    resource: PlanResource = Field(description="What the plan limits")
    used: int = Field(description="What the company has of it")
    limit: int | None = Field(None, description="The plan's limit; null: no limit")


class MonthlyDocumentsResponse(BaseModel):
    model_config = _CONFIG

    period: date = Field(description="First day of the month (Ecuador time)")
    invoices: int = Field(description="Invoices the SRI authorized")
    credit_notes: int = Field(description="Credit notes the SRI authorized")
    total: int = Field(description="Both")


class DocumentsUsageResponse(BaseModel):
    model_config = _CONFIG

    limit: int | None = Field(None, description="Documents a month; null: no limit")
    months: list[MonthlyDocumentsResponse] = Field(
        description="The last six months, the current one last"
    )


class SubscriptionResponse(BaseModel):
    model_config = _CONFIG

    plan: PlanResponse | None = Field(
        None, description="The company's plan; null: no plan configured (no limits)"
    )
    status: SubscriptionStatus = Field(description="Status of the subscription")
    trial_ends_at: datetime | None = Field(None, description="End of the trial")
    read_only: bool = Field(
        description="Suspended, cancelled or trial ended: the company can read but "
        "not create or change data (SUBSCRIPTION_READ_ONLY)"
    )
    resources: list[ResourceUsageResponse] = Field(description="Usage of each limit")
    documents: DocumentsUsageResponse = Field(description="Electronic documents")


class SubscriptionStatusResponse(BaseModel):
    """What every user sees of the company's subscription (`/api/auth/me`)"""

    model_config = _CONFIG

    plan_name: str | None = Field(None, description="The company's plan")
    status: SubscriptionStatus = Field(description="Status of the subscription")
    trial_ends_at: datetime | None = Field(None, description="End of the trial")
    read_only: bool = Field(description="The company can only read")
    documents_limit_reached: bool = Field(
        description="This month's documents reached the plan's limit"
    )
