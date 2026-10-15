from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session
from wireup import injectable

from src.auth.app.repositories import (
    AuthSessionRepository,
    LoginFailureRepository,
    UserRepository,
)
from src.auth.domain.entities import AuthSession, LoginFailure, User
from src.auth.domain.exceptions import (
    EmailAlreadyExistsError,
    UsernameAlreadyExistsError,
)
from src.auth.infra.mappers import AuthSessionMapper, LoginFailureMapper, UserMapper
from src.auth.infra.models import AuthSessionModel, LoginFailureModel, UserModel
from src.shared.infra.repositories import SqlAlchemyRepository


@injectable(lifetime="scoped", as_type=UserRepository)
class SqlAlchemyUserRepository(SqlAlchemyRepository[User], UserRepository):
    __model__ = UserModel
    __unique_errors__ = {
        "ix_users_username": UsernameAlreadyExistsError,
        "ix_users_email": EmailAlreadyExistsError,
    }

    def __init__(self, session: Session, mapper: UserMapper):
        super().__init__(session, mapper)

    def get_by_username(self, username: str) -> User | None:
        return self.first(username=username)

    def get_by_email(self, email: str) -> User | None:
        return self.first(email=email)


@injectable(lifetime="scoped", as_type=AuthSessionRepository)
class SqlAlchemyAuthSessionRepository(
    SqlAlchemyRepository[AuthSession], AuthSessionRepository
):
    __model__ = AuthSessionModel

    def __init__(self, session: Session, mapper: AuthSessionMapper):
        super().__init__(session, mapper)

    def revoke_all_for_user(
        self, user_id: int, now: datetime, keep_session_id: int | None = None
    ) -> int:
        statement = (
            update(AuthSessionModel)
            .where(AuthSessionModel.user_id == user_id)
            .where(AuthSessionModel.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        if keep_session_id is not None:
            statement = statement.where(AuthSessionModel.id != keep_session_id)
        result = self.session.execute(statement)
        self.session.flush()
        return result.rowcount


@injectable(lifetime="scoped", as_type=LoginFailureRepository)
class SqlAlchemyLoginFailureRepository(LoginFailureRepository):
    def __init__(self, session: Session, mapper: LoginFailureMapper):
        self.session = session
        self.mapper = mapper

    def add(self, failure: LoginFailure) -> None:
        self.session.add(LoginFailureModel(**self.mapper.to_dict(failure)))
        self.session.flush()

    def last_failure_at(
        self, *, username: str | None = None, ip_address: str | None = None
    ) -> datetime | None:
        statement = select(func.max(LoginFailureModel.attempted_at))
        return self.session.scalar(_by_key(statement, username, ip_address))

    def count_since(
        self,
        since: datetime,
        *,
        username: str | None = None,
        ip_address: str | None = None,
    ) -> int:
        statement = select(func.count(LoginFailureModel.id)).where(
            LoginFailureModel.attempted_at > since
        )
        return self.session.scalar(_by_key(statement, username, ip_address)) or 0

    def clear_for_username(self, username: str) -> None:
        self.session.execute(
            delete(LoginFailureModel).where(LoginFailureModel.username == username)
        )
        self.session.flush()

    def purge_before(self, before: datetime) -> None:
        self.session.execute(
            delete(LoginFailureModel).where(LoginFailureModel.attempted_at < before)
        )
        self.session.flush()


def _by_key(statement, username: str | None, ip_address: str | None):
    """Failures of a username, or of a client IP"""
    if username is not None:
        return statement.where(LoginFailureModel.username == username)
    if ip_address is not None:
        return statement.where(LoginFailureModel.ip_address == ip_address)
    raise ValueError("username or ip_address is required")
