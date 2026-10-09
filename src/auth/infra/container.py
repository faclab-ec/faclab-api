from src.auth.app.commands.activate_user import ActivateUserCommandHandler
from src.auth.app.commands.admin_reset_password import AdminResetPasswordCommandHandler
from src.auth.app.commands.change_password import ChangePasswordCommandHandler
from src.auth.app.commands.create_user import CreateUserCommandHandler
from src.auth.app.commands.deactivate_user import DeactivateUserCommandHandler
from src.auth.app.commands.login import LoginCommandHandler
from src.auth.app.commands.logout import LogoutCommandHandler
from src.auth.app.commands.refresh_token import RefreshTokenCommandHandler
from src.auth.app.commands.update_user_role import UpdateUserRoleCommandHandler
from src.auth.app.queries.get_users import (
    GetUserByIdQueryHandler,
    ListUsersQueryHandler,
)
from src.auth.infra.mappers import AuthSessionMapper, UserMapper
from src.auth.infra.password_hasher import BcryptPasswordHasher
from src.auth.infra.repositories import (
    SqlAlchemyAuthSessionRepository,
    SqlAlchemyUserRepository,
)
from src.auth.infra.token_service import JwtTokenService

INJECTABLES = [
    UserMapper,
    AuthSessionMapper,
    BcryptPasswordHasher,
    JwtTokenService,
    SqlAlchemyUserRepository,
    SqlAlchemyAuthSessionRepository,
    CreateUserCommandHandler,
    LoginCommandHandler,
    LogoutCommandHandler,
    RefreshTokenCommandHandler,
    ChangePasswordCommandHandler,
    UpdateUserRoleCommandHandler,
    DeactivateUserCommandHandler,
    ActivateUserCommandHandler,
    AdminResetPasswordCommandHandler,
    ListUsersQueryHandler,
    GetUserByIdQueryHandler,
]
