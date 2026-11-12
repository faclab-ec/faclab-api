"""Supplier returns (S5.7): the draft takes received order lines, and
confirming locks them, publishes the stock out and credits the accounts
payable, in that order."""

from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.organization.domain.numbering import DocumentType
from src.purchasing.app.commands.supplier_return import (
    AddSupplierReturnItemCommand,
    AddSupplierReturnItemCommandHandler,
    ConfirmSupplierReturnCommand,
    ConfirmSupplierReturnCommandHandler,
    CreateSupplierReturnCommand,
    CreateSupplierReturnCommandHandler,
    UpdateSupplierReturnItemCommand,
    UpdateSupplierReturnItemCommandHandler,
)
from src.purchasing.domain.entities import (
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderStatus,
    SupplierReturn,
    SupplierReturnItem,
    SupplierReturnStatus,
)
from src.purchasing.domain.events import SupplierReturnConfirmed
from src.purchasing.domain.exceptions import (
    ExceedsReturnableQuantityError,
    InvalidSupplierReturnStatusError,
    PurchaseOrderNotReturnableError,
    SupplierReturnItemOutsideOrderError,
)
from src.shared.app.audit import AuditAction
from src.shared.domain.tax import TaxCode
from tests.audit import FakeAuditTrail
from tests.quantities import FakeProductQuantities

ZERO = Decimal("0")


def _order_item(**overrides) -> PurchaseOrderItem:
    defaults: dict[str, Any] = {
        "id": 1,
        "purchase_order_id": 1,
        "product_id": 5,
        "quantity_ordered": Decimal(10),
        "quantity_received": Decimal(10),
        "unit_cost": Decimal("2.50"),
        "tax_code": TaxCode.VAT_15,
    }
    defaults.update(overrides)
    item = PurchaseOrderItem(**defaults)
    item.recalculate_tax()
    return item


def _return(**overrides) -> SupplierReturn:
    defaults: dict[str, Any] = {
        "id": 3,
        "supplier_id": 10,
        "purchase_order_id": 1,
        "number": "DP-2026-0001",
    }
    defaults.update(overrides)
    return SupplierReturn(**defaults)


def _echo(repo: MagicMock) -> MagicMock:
    repo.create.side_effect = lambda entity: entity
    repo.update.side_effect = lambda entity: entity
    return repo


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def test_a_return_is_created_for_an_order_with_goods_received():
    repo = MagicMock()
    repo.create.side_effect = lambda entity: entity
    po_repo = MagicMock()
    po_repo.get_by_id.return_value = PurchaseOrder(
        id=1,
        supplier_id=10,
        order_number="PO-2026-0001",
        status=PurchaseOrderStatus.PARTIAL,
    )
    po_items = MagicMock()
    po_items.filter_by.return_value = [_order_item(quantity_received=Decimal(4))]
    numbering = MagicMock()
    numbering.next_in_tenant.return_value = "DP-2026-0007"

    result = CreateSupplierReturnCommandHandler(
        repo, po_repo, po_items, numbering
    ).handle(CreateSupplierReturnCommand(purchase_order_id=1, notes="Golpeados"))

    assert (result["supplier_id"], result["purchase_order_id"]) == (10, 1)
    assert (result["number"], result["status"]) == (
        "DP-2026-0007",
        SupplierReturnStatus.DRAFT,
    )
    assert numbering.next_in_tenant.call_args.args[0] == DocumentType.SUPPLIER_RETURN


def test_an_order_with_nothing_left_to_return_has_no_return():
    po_repo = MagicMock()
    po_repo.get_by_id.return_value = PurchaseOrder(
        id=1,
        supplier_id=10,
        order_number="PO-2026-0001",
        status=PurchaseOrderStatus.SENT,
    )
    po_items = MagicMock()
    po_items.filter_by.return_value = [_order_item(quantity_received=Decimal(0))]
    numbering = MagicMock()

    with pytest.raises(PurchaseOrderNotReturnableError):
        CreateSupplierReturnCommandHandler(
            MagicMock(), po_repo, po_items, numbering
        ).handle(CreateSupplierReturnCommand(purchase_order_id=1))
    numbering.next_in_tenant.assert_not_called()


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------


def _item_handler(
    supplier_return: SupplierReturn,
    order_item: PurchaseOrderItem,
    lines: list[SupplierReturnItem],
):
    repo = _echo(MagicMock())
    repo.get_by_id.return_value = supplier_return
    items = _echo(MagicMock())
    items.filter_by.return_value = lines
    po_items = MagicMock()
    po_items.get_by_id.return_value = order_item
    return repo, items, po_items


def test_a_line_takes_the_order_line_and_updates_the_totals():
    supplier_return = _return()
    order_item = _order_item(quantity_returned=Decimal(4))
    repo, items, po_items = _item_handler(supplier_return, order_item, [])
    added: list[SupplierReturnItem] = []
    items.create.side_effect = lambda entity: added.append(entity) or entity
    items.filter_by.side_effect = lambda **_: added

    result = AddSupplierReturnItemCommandHandler(
        repo, items, po_items, FakeProductQuantities()
    ).handle(
        AddSupplierReturnItemCommand(
            supplier_return_id=3,
            purchase_order_item_id=1,
            quantity=Decimal(6),
            location_id=8,
        )
    )

    assert (result["quantity"], result["base_quantity"], result["location_id"]) == (
        Decimal(6),
        Decimal(6),
        8,
    )
    assert (result["subtotal"], result["tax_amount"]) == (
        Decimal("15.00"),
        Decimal("2.25"),
    )
    assert (supplier_return.subtotal, supplier_return.tax, supplier_return.total) == (
        Decimal("15.00"),
        Decimal("2.25"),
        Decimal("17.25"),
    )


def test_the_draft_returns_at_most_what_is_returnable():
    """6 received units are left (10 received, 4 returned): a draft that already
    takes 5 of them can't add 2 more"""
    supplier_return = _return()
    order_item = _order_item(quantity_returned=Decimal(4))
    taken = SupplierReturnItem.of(3, order_item, Decimal(5), None)
    taken.id = 20
    repo, items, po_items = _item_handler(supplier_return, order_item, [taken])

    handler = AddSupplierReturnItemCommandHandler(
        repo, items, po_items, FakeProductQuantities()
    )
    with pytest.raises(ExceedsReturnableQuantityError, match="Only 1 units"):
        handler.handle(
            AddSupplierReturnItemCommand(
                supplier_return_id=3, purchase_order_item_id=1, quantity=Decimal(2)
            )
        )
    items.create.assert_not_called()


def test_changing_a_line_doesnt_count_it_twice():
    supplier_return = _return()
    order_item = _order_item()
    line = SupplierReturnItem.of(3, order_item, Decimal(5), None)
    line.id = 20
    repo, items, po_items = _item_handler(supplier_return, order_item, [line])
    items.get_by_id.return_value = line

    result = UpdateSupplierReturnItemCommandHandler(
        repo, items, po_items, FakeProductQuantities()
    ).handle(
        UpdateSupplierReturnItemCommand(id=20, quantity=Decimal(10), location_id=2)
    )

    assert (result["quantity"], result["location_id"]) == (Decimal(10), 2)


def test_a_line_of_another_order_is_refused():
    supplier_return = _return(purchase_order_id=1)
    repo, items, po_items = _item_handler(
        supplier_return, _order_item(purchase_order_id=2), []
    )

    with pytest.raises(SupplierReturnItemOutsideOrderError):
        AddSupplierReturnItemCommandHandler(
            repo, items, po_items, FakeProductQuantities()
        ).handle(
            AddSupplierReturnItemCommand(
                supplier_return_id=3, purchase_order_item_id=1, quantity=Decimal(1)
            )
        )


def test_a_confirmed_return_takes_no_lines():
    repo, items, po_items = _item_handler(
        _return(status=SupplierReturnStatus.CONFIRMED), _order_item(), []
    )

    with pytest.raises(InvalidSupplierReturnStatusError):
        AddSupplierReturnItemCommandHandler(
            repo, items, po_items, FakeProductQuantities()
        ).handle(
            AddSupplierReturnItemCommand(
                supplier_return_id=3, purchase_order_item_id=1, quantity=Decimal(1)
            )
        )


# ---------------------------------------------------------------------------
# Confirm
# ---------------------------------------------------------------------------


def _confirm_handler(
    supplier_return: SupplierReturn,
    lines: list[SupplierReturnItem],
    order_items: list[PurchaseOrderItem],
    credited: Decimal,
):
    calls: list[str] = []
    repo = _echo(MagicMock())
    repo.first_for_update.return_value = supplier_return
    items = MagicMock()
    items.filter_by.return_value = lines
    po_items = _echo(MagicMock())
    po_items.lock.side_effect = lambda ids: calls.append("lock") or order_items
    publisher = MagicMock()
    publisher.publish.side_effect = lambda *a, **k: calls.append("publish")
    accounts = MagicMock()
    accounts.credit_return.side_effect = lambda **_: calls.append("credit") or credited
    audit = FakeAuditTrail()
    handler = ConfirmSupplierReturnCommandHandler(
        repo, items, po_items, accounts, publisher, MagicMock(), audit
    )
    return handler, po_items, publisher, accounts, audit, calls


def test_confirming_locks_the_lines_moves_the_stock_and_credits_the_supplier():
    order_item = _order_item(
        presentation_id=9, unit_factor=Decimal(12), unit_cost=Decimal("30.00")
    )
    supplier_return = _return()
    lines = [SupplierReturnItem.of(3, order_item, Decimal(2), location_id=4)]
    supplier_return.recalculate_totals(lines)
    handler, po_items, publisher, accounts, audit, calls = _confirm_handler(
        supplier_return, lines, [order_item], credited=Decimal("50.00")
    )

    result = handler.handle(
        ConfirmSupplierReturnCommand(
            id=3, supplier_credit_note_number="001-001-000000045", confirmed_by="Ana"
        )
    )

    assert calls == ["lock", "publish", "credit"]
    assert list(po_items.lock.call_args.args[0]) == [1]
    assert order_item.quantity_returned == Decimal(2)
    event = publisher.publish.call_args.args[0]
    assert isinstance(event, SupplierReturnConfirmed)
    # The stock leaves in base units: 2 boxes of 12
    assert event.items == [{"product_id": 5, "quantity": Decimal(24), "location_id": 4}]
    assert accounts.credit_return.call_args.kwargs == {
        "supplier_id": 10,
        "purchase_order_id": 1,
        "supplier_return_id": 3,
        "amount": Decimal("69.00"),
    }
    assert result["status"] == SupplierReturnStatus.CONFIRMED
    assert (result["credited_amount"], result["refund_due"]) == (
        Decimal("50.00"),
        Decimal("19.00"),
    )
    assert audit.actions == [AuditAction.SUPPLIER_RETURN_CONFIRMED]


def test_confirming_counts_every_line_of_an_order_line_against_it():
    order_item = _order_item(quantity_received=Decimal(5))
    lines = [
        SupplierReturnItem.of(3, order_item, Decimal(3), location_id=1),
        SupplierReturnItem.of(3, order_item, Decimal(3), location_id=2),
    ]
    supplier_return = _return()
    handler, *_ = _confirm_handler(supplier_return, lines, [order_item], ZERO)

    with pytest.raises(ExceedsReturnableQuantityError):
        handler.handle(ConfirmSupplierReturnCommand(id=3))
