from sqlalchemy.orm import Session
from wireup import injectable

from src.auth.app.repositories import UserRepository
from src.auth.domain.entities import User
from src.auth.domain.exceptions import (
    EmailAlreadyExistsError,
    UsernameAlreadyExistsError,
)
from src.auth.infra.mappers import UserMapper
from src.auth.infra.models import UserModel
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
