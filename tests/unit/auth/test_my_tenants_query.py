from unittest.mock import Mock

import pytest

from src.auth.app.queries.get_my_tenants import (
    GetMyTenantsQuery,
    GetMyTenantsQueryHandler,
)
from src.auth.domain.entities import Role
from src.tenancy.app.types import TenantAccess
from src.tenancy.domain.entities import Membership, Tenant
from src.tenancy.domain.exceptions import TenantNotFoundError

A = Tenant(ruc="1799999990001", legal_name="Empresa A")
B = Tenant(ruc="0999999999001", legal_name="Empresa B")


def test_returns_the_session_tenant_and_the_ones_to_switch_to():
    tenants = Mock()
    tenants.get.return_value = A
    memberships = Mock()
    memberships.active_accesses.return_value = [
        TenantAccess(A, Membership(tenant_id=A.id, user_id=1, role=Role.ADMIN)),
        TenantAccess(B, Membership(tenant_id=B.id, user_id=1, role=Role.VIEWER)),
    ]

    result = GetMyTenantsQueryHandler(tenants, memberships).handle(
        GetMyTenantsQuery(tenant_id=A.id, user_id=1)
    )

    tenants.get.assert_called_once_with(A.id)
    memberships.active_accesses.assert_called_once_with(1)
    assert result["tenant"]["ruc"] == A.ruc
    assert [(t["ruc"], t["role"]) for t in result["tenants"]] == [
        (A.ruc, Role.ADMIN),
        (B.ruc, Role.VIEWER),
    ]


def test_a_missing_tenant_is_not_found():
    tenants = Mock()
    tenants.get.return_value = None

    with pytest.raises(TenantNotFoundError):
        GetMyTenantsQueryHandler(tenants, Mock()).handle(
            GetMyTenantsQuery(tenant_id=A.id, user_id=1)
        )
