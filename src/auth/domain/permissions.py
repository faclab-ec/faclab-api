from enum import StrEnum

from src.auth.domain.entities import Role


class Permission(StrEnum):
    # Catalog
    PRODUCT_READ = "product:read"
    PRODUCT_WRITE = "product:write"
    CATEGORY_WRITE = "category:write"
    UOM_WRITE = "uom:write"

    # Inventory
    STOCK_READ = "stock:read"
    MOVEMENT_WRITE = "movement:write"
    WAREHOUSE_WRITE = "warehouse:write"
    LOCATION_WRITE = "location:write"
    LOT_WRITE = "lot:write"
    SERIAL_WRITE = "serial:write"
    ADJUSTMENT_WRITE = "adjustment:write"
    TRANSFER_WRITE = "transfer:write"
    ALERT_READ = "alert:read"

    # Sales
    SALE_READ = "sale:read"
    SALE_WRITE = "sale:write"
    SALE_CANCEL = "sale:cancel"

    # Purchasing
    PURCHASE_READ = "purchase:read"
    PURCHASE_WRITE = "purchase:write"
    PURCHASE_CONFIRM = "purchase:confirm"
    PURCHASE_RECEIVE = "purchase:receive"

    # Partners
    CUSTOMER_READ = "customer:read"
    CUSTOMER_WRITE = "customer:write"
    SUPPLIER_READ = "supplier:read"
    SUPPLIER_WRITE = "supplier:write"

    # POS
    POS_OPERATE = "pos:operate"
    REFUND_APPROVE = "refund:approve"

    # Reports
    REPORT_INVENTORY_READ = "report:inventory:read"
    REPORT_POS_READ = "report:pos:read"

    # Organization: branches, emission points and POS terminals
    ORGANIZATION_READ = "organization:read"
    ORGANIZATION_WRITE = "organization:write"

    # Admin
    USER_MANAGE = "user:manage"


_ALL_READS = frozenset(
    {
        Permission.PRODUCT_READ,
        Permission.STOCK_READ,
        Permission.SALE_READ,
        Permission.PURCHASE_READ,
        Permission.CUSTOMER_READ,
        Permission.SUPPLIER_READ,
        Permission.ALERT_READ,
        Permission.REPORT_INVENTORY_READ,
        Permission.REPORT_POS_READ,
        Permission.ORGANIZATION_READ,
    }
)

# The structure (SRI establishments and emission points) is the admin's
_MANAGER_PERMS = frozenset(Permission) - frozenset(
    {Permission.USER_MANAGE, Permission.POS_OPERATE, Permission.ORGANIZATION_WRITE}
)

_OPERATOR_PERMS = frozenset(
    {
        Permission.PRODUCT_READ,
        Permission.PRODUCT_WRITE,
        Permission.CATEGORY_WRITE,
        Permission.UOM_WRITE,
        Permission.STOCK_READ,
        Permission.MOVEMENT_WRITE,
        Permission.LOT_WRITE,
        Permission.SERIAL_WRITE,
        Permission.ADJUSTMENT_WRITE,
        Permission.TRANSFER_WRITE,
        Permission.ALERT_READ,
        Permission.SALE_READ,
        Permission.SALE_WRITE,
        Permission.PURCHASE_READ,
        Permission.PURCHASE_WRITE,
        Permission.CUSTOMER_READ,
        Permission.CUSTOMER_WRITE,
        Permission.SUPPLIER_READ,
        Permission.SUPPLIER_WRITE,
        Permission.REPORT_INVENTORY_READ,
        Permission.ORGANIZATION_READ,
    }
)

_CASHIER_PERMS = frozenset(
    {
        Permission.POS_OPERATE,
        Permission.SALE_READ,
        Permission.SALE_WRITE,
        Permission.PRODUCT_READ,
        Permission.STOCK_READ,
        Permission.CUSTOMER_READ,
        Permission.CUSTOMER_WRITE,
        Permission.REPORT_POS_READ,
    }
)


PERMISSIONS_BY_ROLE: dict[Role, frozenset[Permission]] = {
    Role.ADMIN: frozenset(Permission),
    Role.MANAGER: _MANAGER_PERMS,
    Role.OPERATOR: _OPERATOR_PERMS,
    Role.VIEWER: _ALL_READS,
    Role.CASHIER: _CASHIER_PERMS,
}


def permissions_for(role: Role) -> frozenset[Permission]:
    return PERMISSIONS_BY_ROLE[role]
