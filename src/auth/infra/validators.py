from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from src.shared.infra.validators import QueryParams


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)


class SelectTenantRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    tenant_id: UUID = Field(description="One of the tenants the login listed")


class TenantResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: UUID
    ruc: str
    legal_name: str
    trade_name: str | None = None


class TenantAccessResponse(TenantResponse):
    role: int = Field(
        description=(
            "The user's role in this tenant "
            "(1=ADMIN, 2=MANAGER, 3=OPERATOR, 4=VIEWER, 5=CASHIER)"
        )
    )


class TokenPairResponse(BaseModel):
    """The refresh token is not here: it goes in the HttpOnly `faclab_refresh`
    cookie."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    access_token: str = Field(description="Short-lived access token")
    token_type: str = Field("Bearer", description="Token scheme")
    expires_in: int = Field(description="Access token lifetime in seconds")
    tenant: TenantResponse = Field(description="The tenant of the session")


class TenantSelectionResponse(BaseModel):
    """Login of a user with several tenants: no session yet. Exchange the
    selection token for one in POST /api/auth/select-tenant."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    selection_token: str = Field(
        description="Send it as `Authorization: Bearer` to select-tenant"
    )
    expires_in: int = Field(description="Selection token lifetime in seconds")
    tenants: list[TenantAccessResponse]


class BranchAccessResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: int = Field(description="Branch ID, the value of `X-Branch-Id`")
    establishment_code: str = Field(description="SRI establishment code")
    name: str
    is_main: bool = Field(description="Whether it is the main branch (matriz)")


class AuthenticatedUserResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: int = Field(ge=1)
    username: str
    full_name: str | None = Field(
        None, description="Shown as the author of documents; username when empty"
    )
    role: int = Field(
        description="Role code (1=ADMIN, 2=MANAGER, 3=OPERATOR, 4=VIEWER, 5=CASHIER)"
    )
    permissions: list[str] = []
    must_change_password: bool = Field(
        False,
        description=(
            "When true, the caller must hit POST /api/auth/change-password before any "
            "permission-gated route; all protected endpoints will return 403 "
            "PASSWORD_CHANGE_REQUIRED."
        ),
    )
    tenant: TenantResponse = Field(
        description="The tenant of the session; role and permissions are those here"
    )
    tenants: list[TenantAccessResponse] = Field(
        default=[],
        description="Every tenant the user can switch to with select-tenant",
    )
    branches: list[BranchAccessResponse] = Field(
        default=[],
        description=(
            "The active branches of the tenant the user may enter, for `X-Branch-Id`"
        ),
    )


class CreateUserRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    username: str = Field(..., min_length=1, max_length=64)
    email: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str | None = Field(
        None,
        max_length=64,
        description="Shown as the author of documents; username when empty",
    )
    role: int = Field(
        4,
        ge=1,
        le=5,
        description="Role code (1=ADMIN, 2=MANAGER, 3=OPERATOR, 4=VIEWER, 5=CASHIER)",
    )


class UpdateUserRoleRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    role: int = Field(
        ...,
        ge=1,
        le=5,
        description="Role code (1=ADMIN, 2=MANAGER, 3=OPERATOR, 4=VIEWER, 5=CASHIER)",
    )


class UserBranchesRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    branch_ids: list[int] = Field(
        description=(
            "Branches of the tenant the user may enter; empty: all of them. "
            "Applies from the user's next login or token refresh"
        ),
        max_length=1000,
    )


class UserBranchesResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    user_id: int
    branch_ids: list[int] = Field(
        description="Branches the user is limited to; empty: all of them"
    )


class UpdateUserProfileRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    full_name: str | None = Field(
        None,
        max_length=64,
        description="Shown as the author of documents; empty or null clears it",
    )


class UserResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: int
    username: str
    email: str
    full_name: str | None = None
    role: int = Field(
        description="Role code (1=ADMIN, 2=MANAGER, 3=OPERATOR, 4=VIEWER, 5=CASHIER)"
    )
    is_active: bool
    must_change_password: bool = False
    last_login_at: datetime | None = None
    created_at: datetime | None = None


class AdminResetPasswordRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    new_password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description=(
            "Temporary password communicated out-of-band to the user. "
            "They will be forced to change it on their next action."
        ),
    )


class UserQueryParams(QueryParams):
    is_active: bool | None = Field(None, description="Filter by active status")
    role: int | None = Field(None, ge=1, le=5, description="Filter by role")
