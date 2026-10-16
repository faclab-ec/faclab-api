import pytest

from src.auth.domain.entities import Role
from src.shared.domain.exceptions import InvalidValueError
from src.tenancy.domain.entities import Membership, Tenant, TenantStatus

RUC = "1799999990001"


def test_a_tenant_is_a_taxpayer_with_a_valid_ruc():
    tenant = Tenant(ruc=f" {RUC} ", legal_name=" Ferretería S.A. ", trade_name=" ")

    assert tenant.ruc == RUC
    assert tenant.legal_name == "Ferretería S.A."
    assert tenant.trade_name is None
    assert tenant.status == TenantStatus.ACTIVE and tenant.is_active
    assert tenant.id != Tenant(ruc=RUC, legal_name="Otra").id


@pytest.mark.parametrize(
    "ruc",
    ["1710034065", "1799999991001", "17999999900AB", ""],
    ids=["cedula", "check-digit", "letters", "empty"],
)
def test_a_tenant_needs_a_valid_13_digit_ruc(ruc):
    with pytest.raises(InvalidValueError):
        Tenant(ruc=ruc, legal_name="Ferretería S.A.")


def test_a_tenant_needs_a_legal_name():
    with pytest.raises(InvalidValueError):
        Tenant(ruc=RUC, legal_name="  ")


def test_a_suspended_tenant_is_not_active():
    tenant = Tenant(ruc=RUC, legal_name="Ferretería S.A.")

    tenant.suspend()
    assert not tenant.is_active
    tenant.activate()
    assert tenant.is_active


def test_a_membership_carries_the_role_in_the_tenant():
    tenant = Tenant(ruc=RUC, legal_name="Ferretería S.A.")
    membership = Membership(tenant_id=tenant.id, user_id=1)

    assert (membership.role, membership.active) == (Role.VIEWER, True)
    assert not membership.is_admin
    membership.change_role(Role.ADMIN)
    membership.deactivate()
    assert membership.is_admin and not membership.active
    membership.activate()
    assert membership.active
