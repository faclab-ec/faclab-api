from fastapi import APIRouter, Depends
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
from src.auth.domain.entities import AuthenticatedUser
from src.auth.infra.dependencies import get_current_user
from src.auth.infra.validators import (
    AuthenticatedUserResponse,
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    TokenPairResponse,
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
            response_model=DataResponse[TokenPairResponse],
            summary="Login with username and password",
            responses=RESPONSES_COMMAND,
        )(self.login)
        self.router.post(
            "/refresh",
            response_model=DataResponse[TokenPairResponse],
            summary="Refresh an access token",
            responses=RESPONSES_COMMAND,
        )(self.refresh)
        self.router.post(
            "/logout",
            status_code=204,
            summary="End the session of a refresh token",
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
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[TokenPairResponse]:
        pair = handler.handle(
            LoginCommand(
                username=credentials.username,
                password=credentials.password,
            )
        )
        return DataResponse(
            data=TokenPairResponse(
                access_token=pair.access_token,
                refresh_token=pair.refresh_token,
                token_type=pair.token_type,
                expires_in=pair.expires_in,
            ),
            meta=meta,
        )

    def refresh(
        self,
        handler: Injected[RefreshTokenCommandHandler],
        request: RefreshRequest,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[TokenPairResponse]:
        pair = handler.handle(RefreshTokenCommand(refresh_token=request.refresh_token))
        return DataResponse(
            data=TokenPairResponse(
                access_token=pair.access_token,
                refresh_token=pair.refresh_token,
                token_type=pair.token_type,
                expires_in=pair.expires_in,
            ),
            meta=meta,
        )

    def logout(
        self,
        handler: Injected[LogoutCommandHandler],
        request: RefreshRequest,
    ) -> None:
        """Revokes the session so its refresh token stops working. Always 204:
        an expired or unknown token leaves nothing to close."""
        handler.handle(LogoutCommand(refresh_token=request.refresh_token))

    def me(
        self,
        user: AuthenticatedUser = Depends(get_current_user),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[AuthenticatedUserResponse]:
        return DataResponse(
            data=AuthenticatedUserResponse(
                id=user.id,
                username=user.username,
                role=int(user.role),
                permissions=sorted(p.value for p in user.permissions),
                must_change_password=user.must_change_password,
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
