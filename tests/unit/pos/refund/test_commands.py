from dataclasses import replace
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.inventory.stock.domain.entities import Stock
from src.pos.refund.app.commands.cancel_refund import (
    CancelRefundCommand,
    CancelRefundCommandHandler,
)
from src.pos.refund.app.commands.create_refund import (
    CreateRefundCommand,
    CreateRefundCommandHandler,
)
from src.pos.refund.app.commands.process_refund import (
    ProcessRefundCommand,
    ProcessRefundCommandHandler,
)
from src.pos.refund.domain.entities import Refund, RefundItem, RefundStatus
from src.pos.refund.domain.exceptions import (
    ExceedsOriginalQuantityError,
    InvalidRefundStatusError,
    RefundItemNotInSaleError,
    SaleNotConfirmedError,
)
from src.pos.shift.domain.entities import Shift, ShiftStatus
from src.pos.shift.domain.exceptions import NoOpenShiftError
from src.sales.domain.entities import Sale, SaleItem, SaleStatus
from src.shared.domain.exceptions import NotFoundError, ValidationError
from src.shared.domain.tax import TaxCode


def _make_sale(**overrides) -> Sale:
    defaults: dict[str, Any] = {
        "id": 1,
        "customer_id": 1,
        "status": SaleStatus.CONFIRMED,
        "subtotal": Decimal("100.00"),
        "tax": Decimal("15.00"),
        "total": Decimal("115.00"),
    }
    defaults.update(overrides)
    return Sale(**defaults)


def _make_sale_item(**overrides) -> SaleItem:
    defaults: dict[str, Any] = {
        "id": 10,
        "sale_id": 1,
        "product_id": 100,
        "quantity": 5,
        "unit_price": Decimal("20.00"),
        "discount": Decimal("0"),
        "tax_code": TaxCode.VAT_15,
        "tax_amount": Decimal("15.00"),
    }
    defaults.update(overrides)
    return SaleItem(**defaults)


def _make_shift(**overrides) -> Shift:
    defaults: dict[str, Any] = {
        "id": 1,
        "cashier_name": "Juan",
        "status": ShiftStatus.OPEN,
    }
    defaults.update(overrides)
    return Shift(**defaults)


def _make_refund(**overrides) -> Refund:
    defaults: dict[str, Any] = {
        "id": 1,
        "original_sale_id": 1,
        "shift_id": 1,
        "subtotal": Decimal("40.00"),
        "tax": Decimal("6.00"),
        "total": Decimal("46.00"),
        "status": RefundStatus.PENDING,
    }
    defaults.update(overrides)
    return Refund(**defaults)


def _make_refund_item(**overrides) -> RefundItem:
    defaults: dict[str, Any] = {
        "id": 1,
        "refund_id": 1,
        "original_sale_item_id": 10,
        "product_id": 100,
        "quantity": 2,
        "unit_price": Decimal("20.00"),
        "discount": Decimal("0"),
        "tax_code": TaxCode.VAT_15,
        "tax_amount": Decimal("6.00"),
    }
    defaults.update(overrides)
    return RefundItem(**defaults)


def _mock_repo(entity=None):
    repo = MagicMock()
    if entity is not None:
        repo.create.return_value = entity
        repo.update.return_value = entity
        repo.get_by_id.return_value = entity
        repo.first.return_value = entity
    else:
        repo.first.return_value = None
        repo.get_by_id.return_value = None
    return repo


# --- CreateRefund ---


class TestCreateRefund:
    def _make_handler(
        self,
        sale=None,
        sale_items=None,
        shift=None,
        prev_refunds=None,
        prev_refund_items=None,
    ):
        sale_repo = _mock_repo(sale)
        sale_item_repo = MagicMock()
        sale_item_repo.filter_by.return_value = sale_items or []
        refund_repo = MagicMock()
        created_refund = Refund(original_sale_id=1, shift_id=1, id=1)
        refund_repo.create.return_value = created_refund
        refund_repo.filter_by.return_value = prev_refunds or []
        refund_item_repo = MagicMock()
        refund_item_repo.filter_by.return_value = prev_refund_items or []
        refund_item_repo.create.side_effect = lambda item: replace(item, id=1)
        shift_repo = MagicMock()
        shift_repo.first.return_value = shift

        handler = CreateRefundCommandHandler(
            sale_repo, sale_item_repo, refund_repo, refund_item_repo, shift_repo
        )
        return handler, refund_repo, refund_item_repo

    def test_happy_path(self):
        sale = _make_sale()
        sale_item = _make_sale_item()
        shift = _make_shift()

        handler, refund_repo, refund_item_repo = self._make_handler(
            sale=sale, sale_items=[sale_item], shift=shift
        )

        command = CreateRefundCommand(
            original_sale_id=1,
            items=[{"sale_item_id": 10, "quantity": 2}],
            reason="Defectuoso",
        )
        result = handler.handle(command)

        assert result["original_sale_id"] == 1
        assert "items" in result
        refund_repo.create.assert_called_once()
        refund_item_repo.create.assert_called_once()
        refund_repo.update.assert_called_once()

    def test_refund_totals_without_sale_discount(self):
        handler, _, _ = self._make_handler(
            sale=_make_sale(), sale_items=[_make_sale_item()], shift=_make_shift()
        )

        result = handler.handle(
            CreateRefundCommand(
                original_sale_id=1, items=[{"sale_item_id": 10, "quantity": 2}]
            )
        )

        # 2 x 20.00 at VAT 15%
        assert (result["subtotal"], result["tax"], result["total"]) == (
            Decimal("40.00"),
            Decimal("6.00"),
            Decimal("46.00"),
        )

    def test_refund_prorates_the_sale_discount(self):
        """Se devuelve lo cobrado: la venta tuvo 10% de descuento global"""
        sale = _make_sale(
            subtotal=Decimal("100.00"),
            discount=Decimal("10.00"),
            discount_type="PERCENTAGE",
            discount_value=Decimal("10"),
            tax=Decimal("13.50"),
            total=Decimal("103.50"),
        )
        handler, _, _ = self._make_handler(
            sale=sale, sale_items=[_make_sale_item()], shift=_make_shift()
        )

        result = handler.handle(
            CreateRefundCommand(
                original_sale_id=1, items=[{"sale_item_id": 10, "quantity": 5}]
            )
        )

        # Refunding every item returns exactly the sale total
        assert (result["subtotal"], result["tax"], result["total"]) == (
            Decimal("90.00"),
            Decimal("13.50"),
            Decimal("103.50"),
        )

    def test_sale_not_found(self):
        handler, _, _ = self._make_handler()

        command = CreateRefundCommand(
            original_sale_id=999, items=[{"sale_item_id": 10, "quantity": 1}]
        )
        with pytest.raises(NotFoundError):
            handler.handle(command)

    def test_sale_not_confirmed(self):
        sale = _make_sale(status=SaleStatus.DRAFT)
        handler, _, _ = self._make_handler(sale=sale)

        command = CreateRefundCommand(
            original_sale_id=1, items=[{"sale_item_id": 10, "quantity": 1}]
        )
        with pytest.raises(SaleNotConfirmedError):
            handler.handle(command)

    def test_no_open_shift(self):
        sale = _make_sale()
        handler, _, _ = self._make_handler(sale=sale, shift=None)

        command = CreateRefundCommand(
            original_sale_id=1, items=[{"sale_item_id": 10, "quantity": 1}]
        )
        with pytest.raises(NoOpenShiftError):
            handler.handle(command)

    def test_item_not_in_sale(self):
        sale = _make_sale()
        sale_item = _make_sale_item(id=10)
        shift = _make_shift()

        handler, _, _ = self._make_handler(
            sale=sale, sale_items=[sale_item], shift=shift
        )

        command = CreateRefundCommand(
            original_sale_id=1, items=[{"sale_item_id": 999, "quantity": 1}]
        )
        with pytest.raises(RefundItemNotInSaleError):
            handler.handle(command)

    def test_exceeds_quantity(self):
        sale = _make_sale()
        sale_item = _make_sale_item(id=10, quantity=3)
        shift = _make_shift()

        handler, _, _ = self._make_handler(
            sale=sale, sale_items=[sale_item], shift=shift
        )

        command = CreateRefundCommand(
            original_sale_id=1, items=[{"sale_item_id": 10, "quantity": 5}]
        )
        with pytest.raises(ExceedsOriginalQuantityError):
            handler.handle(command)

    def test_exceeds_remaining_after_partial_refund(self):
        sale = _make_sale()
        sale_item = _make_sale_item(id=10, quantity=5)
        shift = _make_shift()

        prev_refund = _make_refund(id=2, status=RefundStatus.COMPLETED)
        prev_refund_item = _make_refund_item(
            refund_id=2, original_sale_item_id=10, quantity=3
        )

        handler, _, _ = self._make_handler(
            sale=sale,
            sale_items=[sale_item],
            shift=shift,
            prev_refunds=[prev_refund],
            prev_refund_items=[prev_refund_item],
        )

        command = CreateRefundCommand(
            original_sale_id=1, items=[{"sale_item_id": 10, "quantity": 3}]
        )
        with pytest.raises(ExceedsOriginalQuantityError):
            handler.handle(command)


# --- ProcessRefund ---


class TestProcessRefund:
    def _make_handler(self, refund=None, refund_items=None):
        refund_repo = _mock_repo(refund)
        refund_item_repo = MagicMock()
        refund_item_repo.filter_by.return_value = refund_items or []
        refund_payment_repo = MagicMock()
        refund_payment_repo.create.side_effect = lambda p: p
        movement_repo = MagicMock()
        stock_repo = MagicMock()
        stock_repo.first.return_value = Stock(id=1, product_id=100, quantity=10)
        event_publisher = MagicMock()

        handler = ProcessRefundCommandHandler(
            refund_repo,
            refund_item_repo,
            refund_payment_repo,
            movement_repo,
            stock_repo,
            event_publisher,
        )
        return handler, movement_repo, stock_repo, event_publisher

    def test_happy_path(self):
        refund = _make_refund()
        items = [_make_refund_item()]

        handler, movement_repo, stock_repo, event_publisher = self._make_handler(
            refund=refund, refund_items=items
        )

        command = ProcessRefundCommand(
            refund_id=1,
            payments=[{"amount": "46.00", "payment_method": "CASH"}],
        )
        result = handler.handle(command)

        assert result["status"] == "COMPLETED"
        assert "items" in result
        assert "payments" in result
        movement_repo.create.assert_called_once()
        stock_repo.first.assert_called_once()
        stock_repo.update.assert_called_once()
        assert stock_repo.update.call_args[0][0].quantity == 12
        event_publisher.publish.assert_called_once()

    def test_refund_not_found(self):
        handler, _, _, _ = self._make_handler()

        command = ProcessRefundCommand(
            refund_id=999,
            payments=[{"amount": "50.00", "payment_method": "CASH"}],
        )
        with pytest.raises(NotFoundError):
            handler.handle(command)

    def test_refund_not_pending(self):
        refund = _make_refund(status=RefundStatus.COMPLETED)

        handler, _, _, _ = self._make_handler(refund=refund)

        command = ProcessRefundCommand(
            refund_id=1,
            payments=[{"amount": "46.00", "payment_method": "CASH"}],
        )
        with pytest.raises(InvalidRefundStatusError):
            handler.handle(command)

    def test_insufficient_payment(self):
        refund = _make_refund(total=Decimal("100.00"))
        items = [_make_refund_item()]

        handler, _, _, _ = self._make_handler(refund=refund, refund_items=items)

        command = ProcessRefundCommand(
            refund_id=1,
            payments=[{"amount": "50.00", "payment_method": "CASH"}],
        )
        with pytest.raises(ValidationError):
            handler.handle(command)


# --- CancelRefund ---


class TestCancelRefund:
    def test_happy_path(self):
        refund = _make_refund()
        refund_repo = _mock_repo(refund)
        handler = CancelRefundCommandHandler(refund_repo)

        result = handler.handle(CancelRefundCommand(refund_id=1))

        assert result["status"] == "CANCELLED"
        refund_repo.update.assert_called_once()

    def test_not_found(self):
        refund_repo = _mock_repo()
        handler = CancelRefundCommandHandler(refund_repo)

        with pytest.raises(NotFoundError):
            handler.handle(CancelRefundCommand(refund_id=999))

    def test_not_pending(self):
        refund = _make_refund(status=RefundStatus.COMPLETED)
        refund_repo = _mock_repo(refund)
        handler = CancelRefundCommandHandler(refund_repo)

        with pytest.raises(InvalidRefundStatusError):
            handler.handle(CancelRefundCommand(refund_id=1))
