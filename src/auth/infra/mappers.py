from wireup import injectable

from src.auth.domain.entities import AuthSession, LoginFailure, User
from src.auth.infra.models import AuthSessionModel, LoginFailureModel, UserModel
from src.shared.infra.mappers import Mapper


@injectable(lifetime="singleton")
class UserMapper(Mapper[User, UserModel]):
    __entity__ = User
    __exclude_fields__ = frozenset({"created_at"})


@injectable(lifetime="singleton")
class AuthSessionMapper(Mapper[AuthSession, AuthSessionModel]):
    __entity__ = AuthSession
    __exclude_fields__ = frozenset({"created_at"})


@injectable(lifetime="singleton")
class LoginFailureMapper(Mapper[LoginFailure, LoginFailureModel]):
    __entity__ = LoginFailure
