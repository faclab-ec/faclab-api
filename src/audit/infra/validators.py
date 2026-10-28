from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from src.shared.app.audit import AuditAction
from src.shared.domain.tenant import TenantSource
from src.shared.infra.validators import QueryParams


class AuditEntryResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: int = Field(description="Entry ID")
    occurred_at: datetime = Field(description="When the operation happened")
    actor_user_id: int | None = Field(
        None, description="User who did it (null for a message or a task)"
    )
    actor_name: str | None = Field(
        None, description="The user's full name or username at the time"
    )
    action: AuditAction = Field(description="Audited action")
    resource_type: str = Field(description="Kind of resource (product, sale, user…)")
    resource_id: int | None = Field(None, description="ID of the resource")
    branch_id: int | None = Field(
        None, description="Branch of the resource, or the one the user worked in"
    )
    source: TenantSource = Field(description="request, message or task")
    request_id: str | None = Field(None, description="X-Request-Id of the request")
    before: dict[str, Any] | None = Field(
        None, description="Relevant fields before the operation"
    )
    after: dict[str, Any] | None = Field(
        None, description="Relevant fields after the operation"
    )


class AuditLogQueryParams(QueryParams):
    limit: int | None = Field(
        50, ge=1, le=500, description="Maximum records to return (1-500)"
    )
    from_date: date | None = Field(None, description="Start date (inclusive)")
    to_date: date | None = Field(None, description="End date (inclusive)")
    actor_id: int | None = Field(None, ge=1, description="Filter by user ID")
    action: AuditAction | None = Field(None, description="Filter by action")
    resource_type: str | None = Field(
        None, max_length=32, description="Filter by kind of resource"
    )
    resource_id: int | None = Field(None, ge=1, description="Filter by resource ID")
    branch_id: int | None = Field(None, ge=1, description="Filter by branch ID")
