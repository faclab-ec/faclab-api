from decimal import Decimal

from src.sales.domain.entities import Sale, SaleItem
from src.shared.app.audit import AuditAction, AuditTrail


def audit_price_override(
    audit: AuditTrail, sale: Sale, item: SaleItem, previous_price: Decimal | None
) -> None:
    """A line sold at a price other than its list's: added at another price (POS
    item or quick sale) or changed with PUT .../price"""
    audit.record(
        AuditAction.SALE_PRICE_OVERRIDDEN,
        sale.require_id(),
        before={"unit_price": previous_price},
        after={
            "item_id": item.id,
            "product_id": item.product_id,
            "unit_price": item.unit_price,
            "reason": item.override_reason,
        },
        branch_id=sale.branch_id,
    )
