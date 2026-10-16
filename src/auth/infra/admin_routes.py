from fastapi import APIRouter, Depends
from wireup import Injected

from src.auth.app.commands.activate_user import (
    ActivateUserCommand,
    ActivateUserCommandHandler,
)
from src.auth.app.commands.admin_reset_password import (
    AdminResetPasswordCommand,
    AdminResetPasswordCommandHandler,
)
from src.auth.app.commands.create_user import (
    CreateUserCommand,
    CreateUserCommandHandler,
)
from src.auth.app.commands.deactivate_user import (
    DeactivateUserCommand,
    DeactivateUserCommandHandler,
)
from src.auth.app.commands.update_user_profile import (
    UpdateUserProfileCommand,
    UpdateUserProfileCommandHandler,
)
from src.auth.app.commands.update_user_role import (
    UpdateUserRoleCommand,
    UpdateUserRoleCommandHandler,
)
from src.auth.app.queries.get_users import (
    GetUserByIdQuery,
    GetUserByIdQueryHandler,
    ListUsersQuery,
    ListUsersQueryHandler,
)
from src.auth.domain.entities import AuthenticatedUser
from src.auth.domain.permissions import Permission
from src.auth.infra.dependencies import require_permission
from src.auth.infra.validators import (
    AdminResetPasswordRequest,
    CreateUserRequest,
    UpdateUserProfileRequest,
    UpdateUserRoleRequest,
    UserQueryParams,
    UserResponse,
)
from src.shared.infra.dependencies import get_meta
from src.shared.infra.validators import (
    RESPONSES_COMMAND,
    RESPONSES_LIST,
    RESPONSES_QUERY,
    DataResponse,
    Meta,
    PaginatedDataResponse,
)

# The same callable in the route's dependencies and in its `caller` parameter,
# so FastAPI runs it once per request
_manage = require_permission(Permission.USER_MANAGE)
_perm = [Depends(_manage)]


class UserAdminRouter:
    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        self.router.get(
            "",
            response_model=PaginatedDataResponse[UserResponse],
            summary="List the users of the caller's tenant",
            responses=RESPONSES_LIST,
            dependencies=_perm,
        )(self.list_users)
        self.router.get(
            "/{user_id}",
            response_model=DataResponse[UserResponse],
            summary="Get user by ID",
            responses=RESPONSES_QUERY,
            dependencies=_perm,
        )(self.get_user)
        self.router.post(
            "",
            response_model=DataResponse[UserResponse],
            summary="Create a user in the caller's tenant",
            responses=RESPONSES_COMMAND,
            dependencies=_perm,
        )(self.create_user)
        self.router.put(
            "/{user_id}/role",
            response_model=DataResponse[UserResponse],
            summary="Update the user's role in the caller's tenant",
            responses=RESPONSES_COMMAND,
            dependencies=_perm,
        )(self.update_role)
        self.router.put(
            "/{user_id}/profile",
            response_model=DataResponse[UserResponse],
            summary="Update the user's full name (shown as author of documents)",
            responses=RESPONSES_COMMAND,
            dependencies=_perm,
        )(self.update_profile)
        self.router.post(
            "/{user_id}/activate",
            response_model=DataResponse[UserResponse],
            summary="Give the user back access to the caller's tenant",
            responses=RESPONSES_COMMAND,
            dependencies=_perm,
        )(self.activate)
        self.router.post(
            "/{user_id}/deactivate",
            response_model=DataResponse[UserResponse],
            summary="Remove the user's access to the caller's tenant",
            responses=RESPONSES_COMMAND,
            dependencies=_perm,
        )(self.deactivate)
        self.router.post(
            "/{user_id}/reset-password",
            response_model=DataResponse[UserResponse],
            summary="Reset a user's password (forces must-change on next action)",
            responses=RESPONSES_COMMAND,
            dependencies=_perm,
        )(self.reset_password)

    def list_users(
        self,
        handler: Injected[ListUsersQueryHandler],
        query_params: UserQueryParams = Depends(),
        caller: AuthenticatedUser = Depends(_manage),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[UserResponse]:
        result = handler.handle(
            ListUsersQuery(
                tenant_id=caller.tenant_id,
                **query_params.model_dump(exclude_none=True),
            )
        )
        return PaginatedDataResponse(
            data=[UserResponse.model_validate(u) for u in result["items"]],
            meta=meta.with_pagination(
                total=result["total"],
                limit=result["limit"],
                offset=result["offset"],
            ),
        )

    def get_user(
        self,
        handler: Injected[GetUserByIdQueryHandler],
        user_id: int,
        caller: AuthenticatedUser = Depends(_manage),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[UserResponse]:
        result = handler.handle(
            GetUserByIdQuery(tenant_id=caller.tenant_id, user_id=user_id)
        )
        return DataResponse(data=UserResponse.model_validate(result), meta=meta)

    def create_user(
        self,
        handler: Injected[CreateUserCommandHandler],
        body: CreateUserRequest,
        caller: AuthenticatedUser = Depends(_manage),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[UserResponse]:
        result = handler.handle(
            CreateUserCommand(
                tenant_id=caller.tenant_id,
                username=body.username,
                email=body.email,
                password=body.password,
                role=body.role,
                full_name=body.full_name,
            )
        )
        return DataResponse(data=UserResponse.model_validate(result), meta=meta)

    def update_role(
        self,
        handler: Injected[UpdateUserRoleCommandHandler],
        user_id: int,
        body: UpdateUserRoleRequest,
        caller: AuthenticatedUser = Depends(_manage),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[UserResponse]:
        result = handler.handle(
            UpdateUserRoleCommand(
                tenant_id=caller.tenant_id, user_id=user_id, role=body.role
            )
        )
        return DataResponse(data=UserResponse.model_validate(result), meta=meta)

    def update_profile(
        self,
        handler: Injected[UpdateUserProfileCommandHandler],
        user_id: int,
        body: UpdateUserProfileRequest,
        caller: AuthenticatedUser = Depends(_manage),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[UserResponse]:
        result = handler.handle(
            UpdateUserProfileCommand(
                tenant_id=caller.tenant_id,
                user_id=user_id,
                full_name=body.full_name,
            )
        )
        return DataResponse(data=UserResponse.model_validate(result), meta=meta)

    def activate(
        self,
        handler: Injected[ActivateUserCommandHandler],
        user_id: int,
        caller: AuthenticatedUser = Depends(_manage),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[UserResponse]:
        result = handler.handle(
            ActivateUserCommand(tenant_id=caller.tenant_id, user_id=user_id)
        )
        return DataResponse(data=UserResponse.model_validate(result), meta=meta)

    def deactivate(
        self,
        handler: Injected[DeactivateUserCommandHandler],
        user_id: int,
        caller: AuthenticatedUser = Depends(_manage),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[UserResponse]:
        result = handler.handle(
            DeactivateUserCommand(tenant_id=caller.tenant_id, user_id=user_id)
        )
        return DataResponse(data=UserResponse.model_validate(result), meta=meta)

    def reset_password(
        self,
        handler: Injected[AdminResetPasswordCommandHandler],
        user_id: int,
        body: AdminResetPasswordRequest,
        caller: AuthenticatedUser = Depends(_manage),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[UserResponse]:
        result = handler.handle(
            AdminResetPasswordCommand(
                tenant_id=caller.tenant_id,
                user_id=user_id,
                new_password=body.new_password,
                reset_by_user_id=caller.id,
            )
        )
        return DataResponse(data=UserResponse.model_validate(result), meta=meta)
