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
    ChangePasswordRequest,
    LoginRequest,
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
            description=(
                "Returns the access token and sets the refresh token in the "
                "HttpOnly `faclab_refresh` cookie (Path=/api/auth). Too many "
                "failures lock the username or the client IP: `LOGIN_LOCKED` (429)."
            ),
            responses=RESPONSES_COMMAND,
        )(self.login)
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
    ) -> DataResponse[TokenPairResponse]:
        pair = handler.handle(
            LoginCommand(
                username=credentials.username,
                password=credentials.password,
                ip_address=request.client.host if request.client else None,
            )
        )
        set_refresh_cookie(response, pair.refresh_token)
        return DataResponse(
            data=TokenPairResponse(
                access_token=pair.access_token,
                token_type=pair.token_type,
                expires_in=pair.expires_in,
            ),
            meta=meta,
        )

    def refresh(
        self,
        handler: Injected[RefreshTokenCommandHandler],
        response: Response,
        refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[TokenPairResponse]:
        if not refresh_token:
            raise InvalidTokenError("no refresh token; log in again")
        pair = handler.handle(RefreshTokenCommand(refresh_token=refresh_token))
        set_refresh_cookie(response, pair.refresh_token)
        return DataResponse(
            data=TokenPairResponse(
                access_token=pair.access_token,
                token_type=pair.token_type,
                expires_in=pair.expires_in,
            ),
            meta=meta,
        )

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
        user: AuthenticatedUser = Depends(get_current_user),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[AuthenticatedUserResponse]:
        return DataResponse(
            data=AuthenticatedUserResponse(
                id=user.id,
                username=user.username,
                full_name=user.full_name,
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
