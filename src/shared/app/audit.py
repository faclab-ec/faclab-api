"""Bitácora de auditoría de operaciones sensibles (S3.5).

Cada handler del catálogo registra su entrada con `AuditTrail.record` después
de cambiar el recurso. Se guarda con la sesión de la operación, así que se
confirma o se revierte con ella. El actor, el origen, el id de solicitud y la
sucursal salen del contexto, nunca del comando. Los valores son solo los campos
relevantes: nunca contraseñas, tokens ni correos.
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from enum import StrEnum
from typing import Any


class AuditAction(StrEnum):
    """Catálogo de acciones auditadas, `<recurso>.<verbo>`. Una acción nueva
    necesita su escenario en tests/integration/postgres/test_audit_log.py"""

    PRODUCT_CREATED = "product.created"
    PRODUCT_UPDATED = "product.updated"
    # Cambió el costo, el precio de venta o el código de IVA
    PRODUCT_PRICE_CHANGED = "product.price_changed"
    PRODUCT_DELETED = "product.deleted"
    # A presentation of the product (S5.2): box, roll; its price and cost too
    PRODUCT_PRESENTATION_CREATED = "product.presentation_created"
    PRODUCT_PRESENTATION_UPDATED = "product.presentation_updated"
    PRODUCT_PRESENTATION_DELETED = "product.presentation_deleted"
    # Price lists (S5.3): the list, its prices (resource the list) and the list
    # a customer buys with
    PRICE_LIST_CREATED = "price_list.created"
    PRICE_LIST_UPDATED = "price_list.updated"
    PRICE_LIST_DELETED = "price_list.deleted"
    PRICE_LIST_ITEM_CREATED = "price_list.item_created"
    PRICE_LIST_ITEM_UPDATED = "price_list.item_updated"
    PRICE_LIST_ITEM_DELETED = "price_list.item_deleted"
    CUSTOMER_PRICE_LIST_CHANGED = "customer.price_list_changed"
    # Solo el movimiento manual: los de un documento los audita el documento
    MOVEMENT_CREATED = "movement.created"
    ADJUSTMENT_CONFIRMED = "adjustment.confirmed"
    ADJUSTMENT_CANCELLED = "adjustment.cancelled"
    TRANSFER_CONFIRMED = "transfer.confirmed"
    TRANSFER_RECEIVED = "transfer.received"
    TRANSFER_CANCELLED = "transfer.cancelled"
    SALE_CANCELLED = "sale.cancelled"
    SALE_PRICE_OVERRIDDEN = "sale.price_overridden"
    SALE_DISCOUNT_APPLIED = "sale.discount_applied"
    # Reenvío a faclab-invoicing (POST /sales/{id}/request-invoice)
    SALE_INVOICE_REQUESTED = "sale.invoice_requested"
    # Conciliación con faclab-invoicing (S4.3)
    INVOICE_DISCREPANCY_REVIEWED = "invoice_discrepancy.reviewed"
    # Nota de crédito pedida a mano (S4.5): la factura de una venta anulada, o
    # volver a pedirla. La de una devolución la audita la devolución
    CREDIT_NOTE_REQUESTED = "credit_note.requested"
    CREDIT_NOTE_REQUESTED_AGAIN = "credit_note.requested_again"
    REFUND_PROCESSED = "refund.processed"
    REFUND_CANCELLED = "refund.cancelled"
    CASH_MOVEMENT_REGISTERED = "cash_movement.registered"
    # A customer's payment on account (S5.5), in a shift's cash or outside it
    CUSTOMER_PAYMENT_RECORDED = "customer_payment.recorded"
    # Purchasing (S5.7): goods back to the supplier (stock out, accounts
    # payable credited) and a payment to a supplier
    SUPPLIER_RETURN_CONFIRMED = "supplier_return.confirmed"
    SUPPLIER_PAYMENT_RECORDED = "supplier_payment.recorded"
    SHIFT_OPENED = "shift.opened"
    SHIFT_CLOSED = "shift.closed"
    USER_CREATED = "user.created"
    USER_ROLE_CHANGED = "user.role_changed"
    USER_BRANCHES_CHANGED = "user.branches_changed"
    USER_RENAMED = "user.renamed"
    USER_ACTIVATED = "user.activated"
    USER_DEACTIVATED = "user.deactivated"
    USER_PASSWORD_RESET = "user.password_reset"
    BRANCH_CREATED = "branch.created"
    BRANCH_UPDATED = "branch.updated"
    BRANCH_DELETED = "branch.deleted"
    EMISSION_POINT_CREATED = "emission_point.created"
    EMISSION_POINT_UPDATED = "emission_point.updated"
    EMISSION_POINT_DELETED = "emission_point.deleted"
    POS_TERMINAL_CREATED = "pos_terminal.created"
    POS_TERMINAL_UPDATED = "pos_terminal.updated"
    POS_TERMINAL_DELETED = "pos_terminal.deleted"

    @property
    def resource(self) -> str:
        return self.value.split(".", 1)[0]


class AuditTrail(ABC):
    @abstractmethod
    def record(
        self,
        action: AuditAction,
        resource_id: int | None,
        *,
        before: Mapping[str, Any] | None = None,
        after: Mapping[str, Any] | None = None,
        branch_id: int | None = None,
    ) -> None:
        """Guarda una entrada en la transacción en curso. `branch_id` es la
        sucursal del recurso; sin ella, la del contexto (`X-Branch-Id`)."""
        raise NotImplementedError


def snapshot(source: object, *fields: str) -> dict[str, Any]:
    """Los campos de una entidad tal como están ahora"""
    return {name: getattr(source, name) for name in fields}


def changed(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Los campos de `after` que cambiaron, con su valor anterior y el nuevo"""
    names = [name for name, value in after.items() if before.get(name) != value]
    return {name: before.get(name) for name in names}, {
        name: after[name] for name in names
    }
