"""The scope -> permission table of the integration clients (S6.2).

A scope mapped to the wrong permission opens resources the administrator
never granted (risk §11 of the session), so the whole table is spelled out
here: changing it means changing this test on purpose.
"""

import pytest

from src.auth.domain.permissions import Permission
from src.auth.domain.scopes import (
    PERMISSIONS_BY_SCOPE,
    Scope,
    format_scopes,
    parse_scopes,
    permissions_for_scopes,
)

P = Permission

EXPECTED = {
    Scope.PRODUCTS_READ: {P.PRODUCT_READ},
    Scope.PRODUCTS_WRITE: {P.PRODUCT_WRITE, P.CATEGORY_WRITE, P.UOM_WRITE},
    Scope.PRICES_READ: {P.PRODUCT_READ},
    Scope.PRICES_WRITE: {P.PRODUCT_WRITE},
    Scope.STOCK_READ: {P.STOCK_READ},
    Scope.INVENTORY_WRITE: {P.ADJUSTMENT_WRITE, P.TRANSFER_WRITE},
    Scope.CUSTOMERS_READ: {P.CUSTOMER_READ},
    Scope.CUSTOMERS_WRITE: {P.CUSTOMER_WRITE},
    Scope.SALES_READ: {P.SALE_READ},
    Scope.SALES_WRITE: {P.SALE_WRITE, P.SALE_CANCEL},
    Scope.INVOICES_READ: {P.SALE_READ},
    Scope.WEBHOOKS_MANAGE: set(),
}

# What no integration may ever do, whatever its scopes
NEVER = {
    P.USER_MANAGE,
    P.AUDIT_READ,
    P.ORGANIZATION_WRITE,
    P.IMPORT_WRITE,
    P.INTEGRATION_MANAGE,
    P.POS_OPERATE,
    P.REFUND_APPROVE,
    P.MOVEMENT_WRITE,
    P.PAYABLE_WRITE,
    P.RECEIVABLE_WRITE,
    P.PURCHASE_CONFIRM,
    P.PURCHASE_RECEIVE,
}


def test_every_scope_maps_exactly_to_its_permissions():
    assert {scope: set(perms) for scope, perms in PERMISSIONS_BY_SCOPE.items()} == (
        EXPECTED
    )


def test_the_initial_scopes_of_the_public_api():
    assert {scope.value for scope in Scope} == {
        "products:read",
        "products:write",
        "prices:read",
        "prices:write",
        "stock:read",
        "inventory:write",
        "customers:read",
        "customers:write",
        "sales:read",
        "sales:write",
        "invoices:read",
        "webhooks:manage",
    }


def test_all_the_scopes_together_never_reach_an_admin_permission():
    assert not permissions_for_scopes(Scope) & NEVER


@pytest.mark.parametrize("scope", [s for s in Scope if s.value.endswith(":read")])
def test_a_read_scope_only_reads(scope):
    assert all(p.value.endswith(":read") for p in PERMISSIONS_BY_SCOPE[scope])


def test_permissions_are_the_union_of_the_scopes():
    granted = permissions_for_scopes({Scope.STOCK_READ, Scope.SALES_WRITE})

    assert granted == {P.STOCK_READ, P.SALE_WRITE, P.SALE_CANCEL}


def test_oauth_scope_strings():
    assert parse_scopes("stock:read  sales:write") == {
        Scope.STOCK_READ,
        Scope.SALES_WRITE,
    }
    assert format_scopes({Scope.SALES_WRITE, Scope.STOCK_READ}) == (
        "sales:write stock:read"
    )
    with pytest.raises(ValueError):
        parse_scopes("stock:read users:manage")
