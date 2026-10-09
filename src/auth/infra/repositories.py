from datetime import datetime

from sqlalchemy import update
from sqlalchemy.orm import Session
from wireup import injectable

from src.auth.app.repositories import AuthSessionRepository, UserRepository
from src.auth.domain.entities import AuthSession, User
from src.auth.domain.exceptions import (
    EmailAlreadyExistsError,
    UsernameAlreadyExistsError,
)
from src.auth.infra.mappers import AuthSessionMapper, UserMapper
from src.auth.infra.models import AuthSessionModel, UserModel
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
