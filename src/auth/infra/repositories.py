from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session
from wireup import injectable

from src.auth.app.repositories import (
    AuthSessionRepository,
    LoginFailureRepository,
    UserRepository,
)
from src.auth.app.types import TenantMember
from src.auth.domain.entities import AuthSession, LoginFailure, Role, User
from src.auth.domain.exceptions import (
    EmailAlreadyExistsError,
    UsernameAlreadyExistsError,
)
from src.auth.infra.mappers import AuthSessionMapper, LoginFailureMapper, UserMapper
from src.auth.infra.models import AuthSessionModel, LoginFailureModel, UserModel
from src.shared.infra.repositories import SqlAlchemyRepository
from src.tenancy.infra.mappers import MembershipMapper
from src.tenancy.infra.models import MembershipModel


@injectable(lifetime="scoped", as_type=UserRepository)
class SqlAlchemyUserRepository(SqlAlchemyRepository[User], UserRepository):
    __model__ = UserModel
    __unique_errors__ = {
        "ix_users_username": UsernameAlreadyExistsError,
        "ix_users_email": EmailAlreadyExistsError,
    }

    def __init__(
        self,
        session: Session,
        mapper: UserMapper,
        membership_mapper: MembershipMapper,
    ):
        super().__init__(session, mapper)
        self.membership_mapper = membership_mapper

    def get_by_username(self, username: str) -> User | None:
        return self.first(username=username)

    def get_by_email(self, email: str) -> User | None:
        return self.first(email=email)

    def get_member(self, tenant_id: UUID, user_id: int) -> TenantMember | None:
        statement = _members(tenant_id).where(UserModel.id == user_id)
        row = self.session.execute(statement).first()
        return self._member(row) if row is not None else None

    def paginate_members(
        self,
        tenant_id: UUID,
        *,
        role: Role | None = None,
        is_active: bool | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> dict:
        criteria = []
        if role is not None:
            criteria.append(MembershipModel.role == int(role))
        if is_active is not None:
            criteria.append(MembershipModel.active.is_(is_active))
        statement = _members(tenant_id).where(*criteria).order_by(UserModel.id)
        if limit is not None:
            statement = statement.limit(limit)
        if offset is not None:
            statement = statement.offset(offset)
        total = self.session.scalar(
            select(func.count(MembershipModel.id))
            .where(MembershipModel.tenant_id == tenant_id)
            .where(*criteria)
        )
        return {
            "total": total or 0,
            "limit": limit,
            "offset": offset,
            "items": [
                self._member(row).dict() for row in self.session.execute(statement)
            ],
        }

    def _member(self, row) -> TenantMember:
        user, membership = row
        return TenantMember(
            user=self.mapper.to_entity(user),
            membership=self.membership_mapper.to_entity(membership),
        )


@injectable(lifetime="scoped", as_type=AuthSessionRepository)
class SqlAlchemyAuthSessionRepository(
    SqlAlchemyRepository[AuthSession], AuthSessionRepository
):
    __model__ = AuthSessionModel

    def __init__(self, session: Session, mapper: AuthSessionMapper):
        super().__init__(session, mapper)

    def revoke_all_for_user(
        self,
        user_id: int,
        now: datetime,
        keep_session_id: int | None = None,
        tenant_id: UUID | None = None,
    ) -> int:
        statement = (
            update(AuthSessionModel)
            .where(AuthSessionModel.user_id == user_id)
            .where(AuthSessionModel.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        if keep_session_id is not None:
            statement = statement.where(AuthSessionModel.id != keep_session_id)
        if tenant_id is not None:
            statement = statement.where(AuthSessionModel.tenant_id == tenant_id)
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


def _members(tenant_id: UUID):
    """Users with a membership in the tenant, each with that membership"""
    return (
        select(UserModel, MembershipModel)
        .join(MembershipModel, MembershipModel.user_id == UserModel.id)
        .where(MembershipModel.tenant_id == tenant_id)
    )


def _by_key(statement, username: str | None, ip_address: str | None):
    """Failures of a username, or of a client IP"""
    if username is not None:
        return statement.where(LoginFailureModel.username == username)
    if ip_address is not None:
        return statement.where(LoginFailureModel.ip_address == ip_address)
    raise ValueError("username or ip_address is required")
