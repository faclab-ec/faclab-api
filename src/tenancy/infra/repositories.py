from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import delete, exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from wireup import injectable

from src.auth.domain.entities import Role
from src.auth.infra.models import UserModel
from src.shared.infra.repositories import SqlAlchemyRepository
from src.tenancy.app.repositories import MembershipRepository, TenantRepository
from src.tenancy.app.types import TenantAccess
from src.tenancy.domain.entities import Membership, Tenant, TenantStatus
from src.tenancy.domain.exceptions import (
    MembershipAlreadyExistsError,
    TenantNotFoundError,
    TenantRucAlreadyExistsError,
)
from src.tenancy.infra.mappers import MembershipMapper, TenantMapper
from src.tenancy.infra.models import MembershipModel, TenantModel, UserBranchAccessModel

_RUC_UNIQUE = "tenants_ruc_key"


@injectable(lifetime="scoped", as_type=TenantRepository)
class SqlAlchemyTenantRepository(TenantRepository):
    def __init__(self, session: Session, mapper: TenantMapper):
        self.session = session
        self.mapper = mapper

    def add(self, tenant: Tenant) -> Tenant:
        model = TenantModel(**self.mapper.to_dict(tenant))
        self.session.add(model)
        self._save()
        return self.mapper.to_entity(model)

    def update(self, tenant: Tenant) -> Tenant:
        model = self.session.get(TenantModel, tenant.id)
        if model is None:
            raise TenantNotFoundError()
        for key, value in self.mapper.to_dict(tenant).items():
            setattr(model, key, value)
        self._save()
        return self.mapper.to_entity(model)

    def get(self, tenant_id: UUID) -> Tenant | None:
        return self.mapper.to_entity(self.session.get(TenantModel, tenant_id))

    def get_by_ruc(self, ruc: str) -> Tenant | None:
        model = self.session.scalar(select(TenantModel).where(TenantModel.ruc == ruc))
        return self.mapper.to_entity(model)

    def get_many(self, tenant_ids: Iterable[UUID]) -> list[Tenant]:
        ids = set(tenant_ids)
        if not ids:
            return []
        models = self.session.scalars(
            select(TenantModel).where(TenantModel.id.in_(ids))
        )
        return [self.mapper.to_entity(model) for model in models]

    def _save(self) -> None:
        try:
            self.session.flush()
        except IntegrityError as exc:
            diag = getattr(exc.orig, "diag", None)
            if getattr(diag, "constraint_name", "") == _RUC_UNIQUE:
                raise TenantRucAlreadyExistsError() from exc
            raise


@injectable(lifetime="scoped", as_type=MembershipRepository)
class SqlAlchemyMembershipRepository(
    SqlAlchemyRepository[Membership], MembershipRepository
):
    __model__ = MembershipModel
    __unique_errors__ = {"uq_memberships_tenant_user": MembershipAlreadyExistsError}

    def __init__(
        self, session: Session, mapper: MembershipMapper, tenant_mapper: TenantMapper
    ):
        super().__init__(session, mapper)
        self.tenant_mapper = tenant_mapper

    def get_for(
        self, tenant_id: UUID, user_id: int, for_update: bool = False
    ) -> Membership | None:
        if for_update:
            return self.first_for_update(tenant_id=tenant_id, user_id=user_id)
        return self.first(tenant_id=tenant_id, user_id=user_id)

    def active_accesses(self, user_id: int) -> list[TenantAccess]:
        statement = (
            self._active_access_query(user_id)
            .order_by(TenantModel.legal_name)
            .order_by(TenantModel.ruc)
        )
        return [self._access(row) for row in self.session.execute(statement)]

    def active_access(self, user_id: int, tenant_id: UUID) -> TenantAccess | None:
        statement = self._active_access_query(user_id).where(
            TenantModel.id == tenant_id
        )
        row = self.session.execute(statement).first()
        return self._access(row) if row is not None else None

    def lock_active_admins(self, tenant_id: UUID) -> int:
        statement = (
            select(MembershipModel.id)
            .join(UserModel, UserModel.id == MembershipModel.user_id)
            .where(MembershipModel.tenant_id == tenant_id)
            .where(MembershipModel.role == int(Role.ADMIN))
            .where(MembershipModel.active.is_(True))
            .where(UserModel.is_active.is_(True))
            .with_for_update(of=MembershipModel)
        )
        return len(self.session.scalars(statement).all())

    def has_active_elsewhere(self, user_id: int, tenant_id: UUID) -> bool:
        statement = select(
            exists()
            .where(MembershipModel.user_id == user_id)
            .where(MembershipModel.tenant_id != tenant_id)
            .where(MembershipModel.active.is_(True))
        )
        return bool(self.session.scalar(statement))

    def branch_ids(self, membership_id: int) -> list[int]:
        statement = (
            select(UserBranchAccessModel.branch_id)
            .where(UserBranchAccessModel.membership_id == membership_id)
            .order_by(UserBranchAccessModel.branch_id)
        )
        return list(self.session.scalars(statement))

    def set_branches(self, membership: Membership, branch_ids: Iterable[int]) -> None:
        membership_id = membership.require_id()
        self.session.execute(
            delete(UserBranchAccessModel).where(
                UserBranchAccessModel.membership_id == membership_id
            )
        )
        self.session.add_all(
            UserBranchAccessModel(
                tenant_id=membership.tenant_id,
                membership_id=membership_id,
                branch_id=branch_id,
            )
            for branch_id in sorted(set(branch_ids))
        )
        self.session.flush()

    def _active_access_query(self, user_id: int):
        return (
            select(MembershipModel, TenantModel)
            .join(TenantModel, TenantModel.id == MembershipModel.tenant_id)
            .where(MembershipModel.user_id == user_id)
            .where(MembershipModel.active.is_(True))
            .where(TenantModel.status == TenantStatus.ACTIVE.value)
        )

    def _access(self, row) -> TenantAccess:
        membership, tenant = row
        return TenantAccess(
            tenant=self.tenant_mapper.to_entity(tenant),
            membership=self.mapper.to_entity(membership),
        )
