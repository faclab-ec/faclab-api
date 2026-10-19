from src.auth.app.commands.activate_user import ActivateUserCommandHandler
from src.auth.app.commands.admin_reset_password import AdminResetPasswordCommandHandler
from src.auth.app.commands.change_password import ChangePasswordCommandHandler
from src.auth.app.commands.create_user import CreateUserCommandHandler
from src.auth.app.commands.deactivate_user import DeactivateUserCommandHandler
from src.auth.app.commands.login import LoginCommandHandler
from src.auth.app.commands.logout import LogoutCommandHandler
from src.auth.app.commands.refresh_token import RefreshTokenCommandHandler
from src.auth.app.commands.select_tenant import SelectTenantCommandHandler
from src.auth.app.commands.set_user_branches import SetUserBranchesCommandHandler
from src.auth.app.commands.update_user_profile import UpdateUserProfileCommandHandler
from src.auth.app.commands.update_user_role import UpdateUserRoleCommandHandler
from src.auth.app.queries.get_my_tenants import GetMyTenantsQueryHandler
from src.auth.app.queries.get_user_branches import GetUserBranchesQueryHandler
from src.auth.app.queries.get_users import (
    GetUserByIdQueryHandler,
    ListUsersQueryHandler,
)
from src.auth.infra.lockout import login_lockout_policy
from src.auth.infra.mappers import AuthSessionMapper, LoginFailureMapper, UserMapper
from src.auth.infra.password_hasher import BcryptPasswordHasher
from src.auth.infra.repositories import (
    SqlAlchemyAuthSessionRepository,
    SqlAlchemyLoginFailureRepository,
    SqlAlchemyUserRepository,
)
from src.auth.infra.token_service import JwtTokenService

INJECTABLES = [
    UserMapper,
    AuthSessionMapper,
    LoginFailureMapper,
    login_lockout_policy,
    BcryptPasswordHasher,
    JwtTokenService,
    SqlAlchemyUserRepository,
    SqlAlchemyAuthSessionRepository,
    SqlAlchemyLoginFailureRepository,
    CreateUserCommandHandler,
    LoginCommandHandler,
    LogoutCommandHandler,
    RefreshTokenCommandHandler,
    SelectTenantCommandHandler,
    ChangePasswordCommandHandler,
    UpdateUserRoleCommandHandler,
    UpdateUserProfileCommandHandler,
    DeactivateUserCommandHandler,
    ActivateUserCommandHandler,
    AdminResetPasswordCommandHandler,
    SetUserBranchesCommandHandler,
    GetUserBranchesQueryHandler,
    ListUsersQueryHandler,
    GetUserByIdQueryHandler,
    GetMyTenantsQueryHandler,
]
