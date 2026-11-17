"""Scopes of the integration clients (S6.2, PUBLIC_API.md §3.4).

An integration client is a service principal of its tenant: what it may do is
the scopes its administrator granted, not a role. Each scope stands for the
`Permission`s that guard the same resources for a user, so an integration never
gets more than those (`PERMISSIONS_BY_SCOPE`, tested exhaustively). The public
routes (`/api/v1`, S6.3) declare the scope they need with `require_scope`.
"""

from collections.abc import Iterable
from enum import StrEnum

from src.auth.domain.permissions import Permission


class Scope(StrEnum):
    PRODUCTS_READ = "products:read"
    PRODUCTS_WRITE = "products:write"
    PRICES_READ = "prices:read"
    PRICES_WRITE = "prices:write"
    STOCK_READ = "stock:read"
    INVENTORY_WRITE = "inventory:write"
    CUSTOMERS_READ = "customers:read"
    CUSTOMERS_WRITE = "customers:write"
    SALES_READ = "sales:read"
    SALES_WRITE = "sales:write"
    INVOICES_READ = "invoices:read"
    WEBHOOKS_MANAGE = "webhooks:manage"


PERMISSIONS_BY_SCOPE: dict[Scope, frozenset[Permission]] = {
    # Catalog: products, categories, units of measure and presentations
    Scope.PRODUCTS_READ: frozenset({Permission.PRODUCT_READ}),
    Scope.PRODUCTS_WRITE: frozenset(
        {Permission.PRODUCT_WRITE, Permission.CATEGORY_WRITE, Permission.UOM_WRITE}
    ),
    # Price lists are guarded by the product permissions (S5.3)
    Scope.PRICES_READ: frozenset({Permission.PRODUCT_READ}),
    Scope.PRICES_WRITE: frozenset({Permission.PRODUCT_WRITE}),
    Scope.STOCK_READ: frozenset({Permission.STOCK_READ}),
    # Stock only moves through documents: adjustments and transfers
    Scope.INVENTORY_WRITE: frozenset(
        {Permission.ADJUSTMENT_WRITE, Permission.TRANSFER_WRITE}
    ),
    Scope.CUSTOMERS_READ: frozenset({Permission.CUSTOMER_READ}),
    Scope.CUSTOMERS_WRITE: frozenset({Permission.CUSTOMER_WRITE}),
    Scope.SALES_READ: frozenset({Permission.SALE_READ}),
    # Create, pay and cancel its sales (PUBLIC_API.md §5)
    Scope.SALES_WRITE: frozenset({Permission.SALE_WRITE, Permission.SALE_CANCEL}),
    # The invoices and credit notes of the sales
    Scope.INVOICES_READ: frozenset({Permission.SALE_READ}),
    # Webhook subscriptions (S6.4) have no permission of their own yet
    Scope.WEBHOOKS_MANAGE: frozenset(),
}


def permissions_for_scopes(scopes: Iterable[Scope]) -> frozenset[Permission]:
    granted: set[Permission] = set()
    for scope in scopes:
        granted |= PERMISSIONS_BY_SCOPE[scope]
    return frozenset(granted)


def parse_scopes(value: str | Iterable[str]) -> frozenset[Scope]:
    """The scopes of a space-separated string (OAuth's `scope`) or a list.
    Raises ValueError on an unknown one."""
    names = value.split() if isinstance(value, str) else value
    return frozenset(Scope(name) for name in names)


def format_scopes(scopes: Iterable[Scope]) -> str:
    """OAuth's `scope`: the scopes separated by spaces, sorted"""
    return " ".join(sorted(scope.value for scope in scopes))
