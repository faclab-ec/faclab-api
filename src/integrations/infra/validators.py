from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from src.auth.domain.scopes import Scope
from src.integrations.domain.credentials import IntegrationEnvironment
from src.integrations.domain.entities import (
    MAX_ALLOWED_NETWORKS,
    NAME_MAX_LENGTH,
    IntegrationClientStatus,
)
from src.shared.infra.validators import QueryParams

_CAMEL = ConfigDict(alias_generator=to_camel, populate_by_name=True)
_BranchId = Annotated[int, Field(ge=1)]
_Network = Annotated[str, Field(min_length=2, max_length=43)]


class IntegrationClientRequest(BaseModel):
    model_config = _CAMEL

    name: str = Field(
        min_length=1,
        max_length=NAME_MAX_LENGTH,
        description="Name of the client, the author of what it does",
    )
    scopes: list[Scope] = Field(
        min_length=1,
        max_length=len(Scope),
        description="What it may do (PUBLIC_API.md §3.4)",
    )
    branch_ids: list[_BranchId] | None = Field(
        None,
        max_length=1000,
        description="Branches it may operate in; null or empty: all of them. A "
        "branch that isn't the tenant's: REFERENCE_NOT_FOUND (422)",
    )
    allowed_ips: list[_Network] | None = Field(
        None,
        max_length=MAX_ALLOWED_NETWORKS,
        description="Addresses or networks (CIDR) it may call from; null or empty: any",
    )


class NewClientSecretRequest(BaseModel):
    model_config = _CAMEL

    previous_expires_in_days: int | None = Field(
        None,
        ge=0,
        le=90,
        description="The active secrets stop working in this many days (0: now); "
        "null keeps them until they are revoked",
    )


class ClientSecretResponse(BaseModel):
    model_config = _CAMEL

    id: int = Field(description="Secret ID")
    prefix: str = Field(description="First characters, to recognize it")
    is_active: bool = Field(description="Whether it still gets tokens")
    created_at: datetime | None = Field(None, description="When it was created")
    expires_at: datetime | None = Field(
        None, description="When it stops working (rotation); null: when revoked"
    )
    revoked_at: datetime | None = Field(None, description="When it was revoked")
    last_used_at: datetime | None = Field(
        None, description="Last time it obtained a token"
    )


class CreatedClientSecretResponse(ClientSecretResponse):
    client_secret: str = Field(
        description="The secret. Shown only now: it is kept as a hash"
    )


class IntegrationClientResponse(BaseModel):
    model_config = _CAMEL

    id: int = Field(description="Integration client ID")
    client_id: str = Field(
        description="OAuth client_id: fl_live_… (production) or fl_test_… (sandbox)"
    )
    name: str = Field(description="Name of the client")
    environment: IntegrationEnvironment = Field(
        description="The deployment's environment it belongs to"
    )
    status: IntegrationClientStatus = Field(description="ACTIVE or REVOKED")
    scopes: list[Scope] = Field(description="What it may do")
    branch_ids: list[int] | None = Field(
        None, description="Branches it may operate in; null: all"
    )
    allowed_ips: list[str] | None = Field(
        None, description="Networks it may call from; null: any"
    )
    created_at: datetime | None = Field(None, description="When it was created")
    updated_at: datetime | None = Field(None, description="Last change")
    revoked_at: datetime | None = Field(None, description="When it was revoked")
    last_used_at: datetime | None = Field(None, description="Last token or request")
    secrets: list[ClientSecretResponse] = Field(
        description="Its secrets, never their value"
    )


class CreatedIntegrationClientResponse(IntegrationClientResponse):
    client_secret: str = Field(
        description="Its first secret. Shown only now: it is kept as a hash"
    )


class IntegrationUsageResponse(BaseModel):
    model_config = _CAMEL

    day: date = Field(description="Day")
    token_requests: int = Field(description="Tokens obtained")
    token_failures: int = Field(
        description="Tokens refused (wrong secret, revoked, scope, address)"
    )
    requests: int = Field(description="Requests made with its tokens")
    errors: int = Field(description="Those answered with an error (4xx or 5xx)")
    last_ip: str | None = Field(None, description="Last source address of the day")
    last_seen_at: datetime | None = Field(None, description="Last activity")


class IntegrationClientQueryParams(QueryParams):
    status: IntegrationClientStatus | None = Field(None, description="Filter by status")


class IntegrationUsageQueryParams(BaseModel):
    model_config = _CAMEL

    from_date: date | None = Field(
        None, description="First day (inclusive); default 30 days before toDate"
    )
    to_date: date | None = Field(
        None, description="Last day (inclusive); default today"
    )
