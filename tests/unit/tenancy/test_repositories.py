from collections.abc import Iterator
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from src.auth.domain.entities import Role
from src.auth.infra.mappers import AuthSessionMapper, UserMapper
from src.auth.infra.models import AuthSessionModel, UserModel
from src.auth.infra.repositories import (
    SqlAlchemyAuthSessionRepository,
    SqlAlchemyUserRepository,
)
from src.shared.infra.database import Base
from src.tenancy.domain.entities import Tenant, TenantStatus
from src.tenancy.infra.mappers import MembershipMapper, TenantMapper
from src.tenancy.infra.models import MembershipModel, TenantModel
from src.tenancy.infra.repositories import (
    SqlAlchemyMembershipRepository,
    SqlAlchemyTenantRepository,
)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    tables = [
        Base.metadata.tables[model.__tablename__]
        for model in (UserModel, TenantModel, MembershipModel, AuthSessionModel)
    ]
    Base.metadata.create_all(engine, tables=tables)
    db = sessionmaker(bind=engine)()
    yield db
    db.close()


def _tenant(session, ruc, name, status=TenantStatus.ACTIVE) -> Tenant:
    tenant = Tenant(ruc=ruc, legal_name=name, status=status)
    return SqlAlchemyTenantRepository(session, TenantMapper()).add(tenant)


def _user(session, username, is_active=True) -> int:
    model = UserModel(
        username=username,
        email=f"{username}@example.com",
        password_hash="h",
        is_active=is_active,
    )
    session.add(model)
    session.flush()
    return model.id


def _member(session, tenant, user_id, role=Role.VIEWER, active=True) -> None:
    session.add(
        MembershipModel(
            tenant_id=tenant.id, user_id=user_id, role=int(role), active=active
        )
    )
    session.flush()


def _memberships(session):
    return SqlAlchemyMembershipRepository(session, MembershipMapper(), TenantMapper())


def _users(session):
    return SqlAlchemyUserRepository(session, UserMapper(), MembershipMapper())


def test_tenants_are_found_by_id_and_ruc(session):
    a = _tenant(session, "1799999990001", "Empresa A")
    b = _tenant(session, "0999999999001", "Empresa B")
    repo = SqlAlchemyTenantRepository(session, TenantMapper())

    assert repo.get(a.id) == a
    assert repo.get_by_ruc("0999999999001") == b
    assert repo.get_by_ruc("1790000001001") is None
    assert {t.id for t in repo.get_many([a.id, b.id])} == {a.id, b.id}


def test_only_active_memberships_in_active_tenants_give_access(session):
    zeta = _tenant(session, "1799999990001", "Zeta S.A.")
    alfa = _tenant(session, "0999999999001", "Alfa S.A.")
    suspended = _tenant(
        session, "1790000001001", "Suspendida", status=TenantStatus.SUSPENDED
    )
    left = _tenant(session, "1799000004001", "Ya no trabaja aquí")
    ana = _user(session, "ana")
    for tenant in (zeta, alfa, suspended):
        _member(session, tenant, ana, Role.MANAGER)
    _member(session, left, ana, active=False)
    repo = _memberships(session)

    accesses = repo.active_accesses(ana)

    assert [a.tenant.legal_name for a in accesses] == ["Alfa S.A.", "Zeta S.A."]
    assert accesses[0].membership.role == Role.MANAGER
    assert repo.active_access(ana, zeta.id) is not None
    assert repo.active_access(ana, suspended.id) is None
    assert repo.active_access(ana, left.id) is None


def test_only_active_admins_of_the_tenant_count(session):
    a = _tenant(session, "1799999990001", "Empresa A")
    b = _tenant(session, "0999999999001", "Empresa B")
    _member(session, a, _user(session, "admin"), Role.ADMIN)
    _member(session, a, _user(session, "blocked", is_active=False), Role.ADMIN)
    _member(session, a, _user(session, "former"), Role.ADMIN, active=False)
    _member(session, a, _user(session, "manager"), Role.MANAGER)
    _member(session, b, _user(session, "admin-b"), Role.ADMIN)
    _member(session, b, _user(session, "admin-b2"), Role.ADMIN)
    repo = _memberships(session)

    assert repo.lock_active_admins(a.id) == 1
    assert repo.lock_active_admins(b.id) == 2


def test_a_user_is_elsewhere_only_with_an_active_membership_in_another_tenant(
    session,
):
    a = _tenant(session, "1799999990001", "Empresa A")
    b = _tenant(session, "0999999999001", "Empresa B")
    ana = _user(session, "ana")
    luis = _user(session, "luis")
    _member(session, a, ana)
    _member(session, b, ana)
    _member(session, a, luis)
    _member(session, b, luis, active=False)
    repo = _memberships(session)

    assert repo.has_active_elsewhere(ana, a.id)
    assert not repo.has_active_elsewhere(luis, a.id)


def test_the_users_of_a_tenant_carry_its_role_and_state(session):
    a = _tenant(session, "1799999990001", "Empresa A")
    b = _tenant(session, "0999999999001", "Empresa B")
    ana = _user(session, "ana")
    luis = _user(session, "luis")
    _user(session, "nobody")
    _member(session, a, ana, Role.ADMIN)
    _member(session, a, luis, Role.CASHIER, active=False)
    _member(session, b, ana, Role.VIEWER)
    repo = _users(session)

    page = repo.paginate_members(a.id, limit=10, offset=0)
    assert page["total"] == 2
    assert [(u["username"], u["role"], u["is_active"]) for u in page["items"]] == [
        ("ana", Role.ADMIN, True),
        ("luis", Role.CASHIER, False),
    ]
    cashiers = repo.paginate_members(a.id, role=Role.CASHIER, is_active=False)
    assert (cashiers["total"], cashiers["items"][0]["username"]) == (1, "luis")
    assert repo.paginate_members(b.id)["total"] == 1

    member = repo.get_member(b.id, ana)
    assert member is not None and member.membership.role == Role.VIEWER
    assert repo.get_member(b.id, luis) is None


def test_sessions_can_be_revoked_in_one_tenant_only(session):
    a = _tenant(session, "1799999990001", "Empresa A")
    b = _tenant(session, "0999999999001", "Empresa B")
    ana = _user(session, "ana")
    expires = datetime.now() + timedelta(days=1)
    for tenant in (a, a, b):
        session.add(
            AuthSessionModel(user_id=ana, tenant_id=tenant.id, expires_at=expires)
        )
    session.flush()
    repo = SqlAlchemyAuthSessionRepository(session, AuthSessionMapper())

    assert repo.revoke_all_for_user(ana, datetime.now(), tenant_id=a.id) == 2

    open_tenants = session.scalars(
        select(AuthSessionModel.tenant_id).where(AuthSessionModel.revoked_at.is_(None))
    ).all()
    assert open_tenants == [b.id]
