from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Request, Response
from wireup import Injected

from src.auth.app.commands.change_password import (
    ChangePasswordCommand,
    ChangePasswordCommandHandler,
)
from src.auth.app.commands.login import LoginCommand, LoginCommandHandler
from src.auth.app.commands.logout import LogoutCommand, LogoutCommandHandler
from src.auth.app.commands.refresh_token import (
    RefreshTokenCommand,
    RefreshTokenCommandHandler,
)
from src.auth.app.commands.select_tenant import (
    SelectTenantCommand,
    SelectTenantCommandHandler,
)
from src.auth.app.commands.sessions import OpenedSession
from src.auth.app.queries.get_my_tenants import (
    GetMyTenantsQuery,
    GetMyTenantsQueryHandler,
)
from src.auth.domain.entities import AuthenticatedUser
from src.auth.domain.exceptions import InvalidTokenError
from src.auth.infra.cookies import (
    REFRESH_COOKIE,
    clear_refresh_cookie,
    set_refresh_cookie,
)
from src.auth.infra.dependencies import get_current_user
from src.auth.infra.validators import (
    AuthenticatedUserResponse,
    BranchAccessResponse,
    ChangePasswordRequest,
    LoginRequest,
    SelectTenantRequest,
    TenantAccessResponse,
    TenantResponse,
    TenantSelectionResponse,
    TokenPairResponse,
)
from src.organization.app.queries.branch import (
    GetAccessibleBranchesQuery,
    GetAccessibleBranchesQueryHandler,
)
from src.shared.infra.dependencies import get_meta
from src.shared.infra.validators import (
    RESPONSES_COMMAND,
    RESPONSES_QUERY,
    DataResponse,
    Meta,
)


class AuthRouter:
    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        self.router.post(
            "/login",
            response_model=DataResponse[TokenPairResponse | TenantSelectionResponse],
            summary="Login with username and password",
            description=(
                "A user with one active tenant gets the access token and the "
                "tenant, and the refresh token in the HttpOnly `faclab_refresh` "
                "cookie (Path=/api/auth). A user with several gets a "
                "`selectionToken` and the `tenants` to choose from with "
                "`POST /api/auth/select-tenant`. Without an active tenant: "
                "`NO_ACTIVE_TENANT` (403). Too many failures lock the username or "
                "the client IP: `LOGIN_LOCKED` (429)."
            ),
            responses=RESPONSES_COMMAND,
        )(self.login)
        self.router.post(
            "/select-tenant",
            response_model=DataResponse[TokenPairResponse],
            summary="Open a session in one of the user's tenants",
            description=(
                "Send the login's `selectionToken`, or the current access token to "
                "switch tenants (the current session ends), as "
                "`Authorization: Bearer`. Answers like a one-tenant login and sets "
                "the refresh cookie. A tenant the user can't enter: "
                "`TENANT_ACCESS_DENIED` (403)."
            ),
            responses=RESPONSES_COMMAND,
        )(self.select_tenant)
        self.router.post(
            "/refresh",
            response_model=DataResponse[TokenPairResponse],
            summary="Refresh an access token",
            description=(
                "Reads the refresh token from the `faclab_refresh` cookie and "
                "rotates it. An already used refresh token revokes the session: "
                "`TOKEN_REUSED` (401)."
            ),
            responses=RESPONSES_COMMAND,
        )(self.refresh)
        self.router.post(
            "/logout",
            status_code=204,
            summary="End the session of the refresh cookie and clear it",
            responses=RESPONSES_COMMAND,
        )(self.logout)
        self.router.get(
            "/me",
            response_model=DataResponse[AuthenticatedUserResponse],
            summary="Get the currently authenticated user",
            responses=RESPONSES_QUERY,
        )(self.me)
        self.router.post(
            "/change-password",
            status_code=204,
            summary="Change the current user's password",
            responses=RESPONSES_COMMAND,
        )(self.change_password)

    def login(
        self,
        handler: Injected[LoginCommandHandler],
        credentials: LoginRequest,
        request: Request,
        response: Response,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[TokenPairResponse | TenantSelectionResponse]:
        result = handler.handle(
            LoginCommand(
                username=credentials.username,
                password=credentials.password,
                ip_address=request.client.host if request.client else None,
            )
        )
        if result.session is not None:
            return DataResponse(data=_session(response, result.session), meta=meta)
        if result.selection is None:
            raise RuntimeError("login returned neither a session nor a selection")
        return DataResponse(
            data=TenantSelectionResponse(
                selection_token=result.selection.token,
                expires_in=result.selection.expires_in,
                tenants=[
                    TenantAccessResponse.model_validate(
                        {**access.tenant.dict(), "role": access.membership.role}
                    )
                    for access in result.tenants
                ],
            ),
            meta=meta,
        )

    def select_tenant(
        self,
        handler: Injected[SelectTenantCommandHandler],
        body: SelectTenantRequest,
        request: Request,
        response: Response,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[TokenPairResponse]:
        header = request.headers.get("authorization") or ""
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise InvalidTokenError("no token; log in again")
        session = handler.handle(
            SelectTenantCommand(tenant_id=body.tenant_id, token=token.strip())
        )
        return DataResponse(data=_session(response, session), meta=meta)

    def refresh(
        self,
        handler: Injected[RefreshTokenCommandHandler],
        response: Response,
        refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[TokenPairResponse]:
        if not refresh_token:
            raise InvalidTokenError("no refresh token; log in again")
        session = handler.handle(RefreshTokenCommand(refresh_token=refresh_token))
        return DataResponse(data=_session(response, session), meta=meta)

    def logout(
        self,
        handler: Injected[LogoutCommandHandler],
        response: Response,
        refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
    ) -> None:
        """Revokes the session so its refresh token stops working. Always 204:
        an expired or unknown token leaves nothing to close."""
        if refresh_token:
            handler.handle(LogoutCommand(refresh_token=refresh_token))
        clear_refresh_cookie(response)

    def me(
        self,
        handler: Injected[GetMyTenantsQueryHandler],
        branches_handler: Injected[GetAccessibleBranchesQueryHandler],
        user: AuthenticatedUser = Depends(get_current_user),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[AuthenticatedUserResponse]:
        tenants = handler.handle(
            GetMyTenantsQuery(tenant_id=user.tenant_id, user_id=user.id)
        )
        branches = branches_handler.handle(
            GetAccessibleBranchesQuery(branch_ids=user.branch_ids)
        )
        return DataResponse(
            data=AuthenticatedUserResponse(
                id=user.id,
                username=user.username,
                full_name=user.full_name,
                role=int(user.role),
                permissions=sorted(p.value for p in user.permissions),
                must_change_password=user.must_change_password,
                tenant=TenantResponse.model_validate(tenants["tenant"]),
                tenants=[
                    TenantAccessResponse.model_validate(access)
                    for access in tenants["tenants"]
                ],
                branches=[
                    BranchAccessResponse.model_validate(branch) for branch in branches
                ],
            ),
            meta=meta,
        )

    def change_password(
        self,
        handler: Injected[ChangePasswordCommandHandler],
        body: ChangePasswordRequest,
        user: AuthenticatedUser = Depends(get_current_user),
    ) -> None:
        handler.handle(
            ChangePasswordCommand(
                user_id=user.id,
                current_password=body.current_password,
                new_password=body.new_password,
                keep_session_id=user.session_id,
            )
        )


def _session(response: Response, session: OpenedSession) -> TokenPairResponse:
    """Sets the session's refresh cookie and returns the rest of its tokens"""
    set_refresh_cookie(response, session.pair.refresh_token)
    return TokenPairResponse(
        access_token=session.pair.access_token,
        token_type=session.pair.token_type,
        expires_in=session.pair.expires_in,
        tenant=TenantResponse.model_validate(session.tenant.dict()),
    )
