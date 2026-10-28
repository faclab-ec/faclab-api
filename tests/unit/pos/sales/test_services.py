from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.inventory.movement.domain.constants import MovementType
from src.inventory.movement.domain.entities import Movement
from src.inventory.stock.domain.entities import Stock
from src.pos.terminal.app.stock import TerminalStock
from src.sales.domain.entities import (
    Payment,
    PaymentMethod,
    PaymentStatus,
    Sale,
    SaleItem,
    SaleStatus,
)
from src.sales.domain.exceptions import (
    InsufficientPaymentError,
    InsufficientStockError,
    PaymentExceedsBalanceError,
    SaleHasNoItemsError,
)
from src.shared.domain.exceptions import NotFoundError
from tests.audit import FakeAuditTrail
from tests.unit.pos.terminals import LOCATION_ID, TERMINAL, numbering


def _make_sale(**overrides) -> Sale:
    defaults: dict[str, Any] = {
        "id": 1,
        "customer_id": 10,
        "status": SaleStatus.DRAFT,
        "subtotal": Decimal("1000"),
        "total": Decimal("1000"),
    }
    defaults.update(overrides)
    return Sale(**defaults)


def _make_sale_item(**overrides) -> SaleItem:
    defaults: dict[str, Any] = {
        "id": 1,
        "sale_id": 1,
        "product_id": 100,
        "quantity": 5,
        "unit_price": Decimal("200.00"),
        "discount": Decimal("0"),
    }
    defaults.update(overrides)
    return SaleItem(**defaults)


def _make_payment(**overrides) -> Payment:
    defaults: dict[str, Any] = {
        "id": 1,
        "sale_id": 1,
        "amount": Decimal("1000"),
        "payment_method": PaymentMethod.CASH,
    }
    defaults.update(overrides)
    return Payment(**defaults)


def _make_stock(**overrides) -> Stock:
    defaults: dict[str, Any] = {
        "id": 1,
        "product_id": 100,
        "quantity": 50,
    }
    defaults.update(overrides)
    return Stock(**defaults)


class _Repos:
    """The repositories under the handler's TerminalStock, for the asserts"""

    movement_repo: MagicMock
    stock_repo: MagicMock


def _build_confirm_handler(sale=None, items=None, stock=None, payments=None):
    from src.pos.sales.app.commands import POSConfirmSaleCommandHandler

    class Handler(_Repos, POSConfirmSaleCommandHandler):
        pass

    handler = Handler.__new__(Handler)
    handler.sale_repo = MagicMock()
    handler.sale_item_repo = MagicMock()
    handler.movement_repo = MagicMock()
    handler.stock_repo = MagicMock()
    handler.stock = TerminalStock(handler.stock_repo, handler.movement_repo)
    handler.terminal_repo = MagicMock()
    handler.terminal_repo.get_by_id.return_value = TERMINAL
    handler.numbering = numbering()
    handler.payment_repo = MagicMock()
    # By default paid in full
    handler.payment_repo.filter_by.return_value = (
        [_make_payment()] if payments is None else payments
    )
    handler.event_publisher = MagicMock()
    handler.session = MagicMock()

    if sale is not None:
        handler.sale_repo.get_by_id.return_value = sale
        handler.sale_repo.update.return_value = sale
    if items is not None:
        handler.sale_item_repo.filter_by.return_value = items
    if stock is not None:
        handler.stock_repo.first_for_update.return_value = stock

    return handler


def _build_cancel_handler(sale=None, items=None, stock=None):
    from src.pos.sales.app.commands import POSCancelSaleCommandHandler

    class Handler(_Repos, POSCancelSaleCommandHandler):
        pass

    handler = Handler.__new__(Handler)
    handler.sale_repo = MagicMock()
    handler.sale_item_repo = MagicMock()
    handler.movement_repo = MagicMock()
    handler.movement_repo.filter_by.return_value = []
    handler.stock_repo = MagicMock()
    handler.stock = TerminalStock(handler.stock_repo, handler.movement_repo)
    handler.terminal_repo = MagicMock()
    handler.terminal_repo.get_by_id.return_value = TERMINAL
    handler.event_publisher = MagicMock()
    handler.audit = FakeAuditTrail()

    if sale is not None:
        handler.sale_repo.get_by_id.return_value = sale
        handler.sale_repo.update.return_value = sale
    if items is not None:
        handler.sale_item_repo.filter_by.return_value = items
    if stock is not None:
        handler.stock_repo.first_for_update.return_value = stock

    return handler


# === POSConfirmSaleCommandHandler Tests ===


class TestPOSConfirmSaleCommandHandler:
    def test_confirm_happy_path(self):
        from src.pos.sales.app.commands import POSConfirmSaleCommand

        sale = _make_sale()
        items = [_make_sale_item()]
        stock = _make_stock(quantity=50)

        handler = _build_confirm_handler(sale=sale, items=items, stock=stock)
        result = handler._handle(POSConfirmSaleCommand(sale_id=1))

        assert result["status"] == SaleStatus.CONFIRMED
        handler.sale_repo.update.assert_called_once()
        handler.movement_repo.create.assert_called_once()
        handler.stock_repo.update.assert_called_once()
        assert handler.stock_repo.update.call_args[0][0].quantity == 45

    def test_confirm_takes_from_the_terminal_location_and_numbers_the_sale(self):
        from src.pos.sales.app.commands import POSConfirmSaleCommand

        sale = _make_sale(branch_id=1, terminal_id=TERMINAL.id)
        handler = _build_confirm_handler(
            sale=sale, items=[_make_sale_item()], stock=_make_stock()
        )

        result = handler._handle(POSConfirmSaleCommand(sale_id=1))

        handler.stock_repo.first_for_update.assert_called_once_with(
            product_id=100, location_id=LOCATION_ID
        )
        movement = handler.movement_repo.create.call_args.args[0]
        assert movement.location_id == LOCATION_ID
        assert (movement.reference_type, movement.reference_id) == ("sale", 1)
        handler.numbering.next.assert_called_once_with(1, "SALE")
        assert result["number"] == "V-001-000001"

    def test_confirm_insufficient_stock_raises_error(self):
        from src.pos.sales.app.commands import POSConfirmSaleCommand

        sale = _make_sale()
        items = [_make_sale_item(quantity=10)]
        stock = _make_stock(quantity=3)

        handler = _build_confirm_handler(sale=sale, items=items, stock=stock)

        with pytest.raises(InsufficientStockError):
            handler._handle(POSConfirmSaleCommand(sale_id=1))

        handler.sale_repo.update.assert_not_called()
        handler.movement_repo.create.assert_not_called()

    def test_confirm_no_stock_record_raises_error(self):
        from src.pos.sales.app.commands import POSConfirmSaleCommand

        sale = _make_sale()
        items = [_make_sale_item(quantity=5)]

        handler = _build_confirm_handler(sale=sale, items=items)
        handler.stock_repo.first_for_update.return_value = None

        with pytest.raises(InsufficientStockError):
            handler._handle(POSConfirmSaleCommand(sale_id=1))

    def test_confirm_no_items_raises_error(self):
        from src.pos.sales.app.commands import POSConfirmSaleCommand

        sale = _make_sale()

        handler = _build_confirm_handler(sale=sale, items=[])

        with pytest.raises(SaleHasNoItemsError):
            handler._handle(POSConfirmSaleCommand(sale_id=1))

    def test_confirm_sale_not_found_raises_error(self):
        from src.pos.sales.app.commands import POSConfirmSaleCommand

        handler = _build_confirm_handler()
        handler.sale_repo.get_by_id.return_value = None

        with pytest.raises(NotFoundError):
            handler._handle(POSConfirmSaleCommand(sale_id=999))

    def test_confirm_propagates_unexpected_error(self):
        from src.pos.sales.app.commands import POSConfirmSaleCommand

        sale = _make_sale()
        items = [_make_sale_item()]
        stock = _make_stock(quantity=50)

        handler = _build_confirm_handler(sale=sale, items=items, stock=stock)
        handler.movement_repo.create.side_effect = RuntimeError("DB error")

        with pytest.raises(RuntimeError, match="DB error"):
            handler._handle(POSConfirmSaleCommand(sale_id=1))

    def test_confirm_publishes_event_with_pos_source(self):
        from src.pos.sales.app.commands import POSConfirmSaleCommand
        from src.sales.domain.events import SaleConfirmed

        sale = _make_sale()
        items = [_make_sale_item()]
        stock = _make_stock(quantity=50)

        handler = _build_confirm_handler(sale=sale, items=items, stock=stock)
        handler._handle(POSConfirmSaleCommand(sale_id=1))

        handler.event_publisher.publish.assert_called_once()
        published_event = handler.event_publisher.publish.call_args[0][0]
        assert isinstance(published_event, SaleConfirmed)
        assert published_event.source == "pos"

    def test_confirm_multiple_items(self):
        from src.pos.sales.app.commands import POSConfirmSaleCommand

        sale = _make_sale()
        items = [
            _make_sale_item(id=1, product_id=100, quantity=3),
            _make_sale_item(id=2, product_id=200, quantity=2),
        ]
        stock = _make_stock(quantity=50)

        handler = _build_confirm_handler(sale=sale, items=items, stock=stock)
        result = handler._handle(POSConfirmSaleCommand(sale_id=1))

        assert result["status"] == SaleStatus.CONFIRMED
        assert handler.movement_repo.create.call_count == 2
        assert handler.stock_repo.update.call_count == 2

    def test_confirm_requires_payments_covering_the_total(self):
        from src.pos.sales.app.commands import POSConfirmSaleCommand

        handler = _build_confirm_handler(
            sale=_make_sale(),
            items=[_make_sale_item()],
            stock=_make_stock(),
            payments=[_make_payment(amount=Decimal("999.99"))],
        )

        with pytest.raises(InsufficientPaymentError):
            handler._handle(POSConfirmSaleCommand(sale_id=1))

        # Checked before locking the stock or taking a number
        handler.stock_repo.first_for_update.assert_not_called()
        handler.numbering.next.assert_not_called()
        handler.sale_repo.update.assert_not_called()

    def test_confirm_without_payments_fails(self):
        from src.pos.sales.app.commands import POSConfirmSaleCommand

        handler = _build_confirm_handler(
            sale=_make_sale(), items=[_make_sale_item()], payments=[]
        )

        with pytest.raises(InsufficientPaymentError):
            handler._handle(POSConfirmSaleCommand(sale_id=1))

    def test_confirm_applies_the_payments_to_the_final_total(self):
        """A draft paid before its items changed: the cash handed over in excess
        is change, and only what was applied reaches the event"""
        from src.pos.sales.app.commands import POSConfirmSaleCommand

        card = _make_payment(
            id=1, amount=Decimal("300"), payment_method=PaymentMethod.CREDIT_CARD
        )
        cash = _make_payment(id=2, amount=Decimal("800"))
        sale = _make_sale()
        handler = _build_confirm_handler(
            sale=sale,
            items=[_make_sale_item()],
            stock=_make_stock(),
            # Not in the order they were taken
            payments=[cash, card],
        )

        handler._handle(POSConfirmSaleCommand(sale_id=1))

        assert (card.amount, card.change) == (Decimal("300"), Decimal("0"))
        assert (cash.amount, cash.amount_tendered, cash.change) == (
            Decimal("700"),
            Decimal("800"),
            Decimal("100"),
        )
        assert handler.payment_repo.update.call_count == 2
        assert sale.payment_status == PaymentStatus.PAID
        event = handler.event_publisher.publish.call_args.args[0]
        assert [p["amount"] for p in event.payments] == [Decimal("300"), Decimal("700")]

    def test_confirm_rejects_a_card_payment_above_the_total(self):
        from src.pos.sales.app.commands import POSConfirmSaleCommand

        handler = _build_confirm_handler(
            sale=_make_sale(),
            items=[_make_sale_item()],
            payments=[
                _make_payment(
                    amount=Decimal("1200"), payment_method=PaymentMethod.DEBIT_CARD
                )
            ],
        )

        with pytest.raises(PaymentExceedsBalanceError):
            handler._handle(POSConfirmSaleCommand(sale_id=1))


# === POSCancelSaleCommandHandler Tests ===


class TestPOSCancelSaleCommandHandler:
    def test_cancel_draft_sale(self):
        from src.pos.sales.app.commands import POSCancelSaleCommand

        sale = _make_sale(status=SaleStatus.DRAFT)

        handler = _build_cancel_handler(sale=sale)
        result = handler._handle(POSCancelSaleCommand(sale_id=1))

        assert result["status"] == SaleStatus.CANCELLED
        handler.movement_repo.create.assert_not_called()
        handler.stock_repo.update.assert_not_called()

    def test_cancel_confirmed_sale_reverses_inventory(self):
        from src.pos.sales.app.commands import POSCancelSaleCommand

        sale = _make_sale(status=SaleStatus.CONFIRMED)
        items = [_make_sale_item()]
        stock = _make_stock(quantity=45)

        handler = _build_cancel_handler(sale=sale, items=items, stock=stock)
        result = handler._handle(POSCancelSaleCommand(sale_id=1))

        assert result["status"] == SaleStatus.CANCELLED
        handler.movement_repo.create.assert_called_once()
        handler.stock_repo.update.assert_called_once()
        assert handler.stock_repo.update.call_args[0][0].quantity == 50

    def test_cancel_puts_back_where_the_sale_took_from(self):
        from src.pos.sales.app.commands import POSCancelSaleCommand

        sale = _make_sale(status=SaleStatus.CONFIRMED, terminal_id=TERMINAL.id)
        handler = _build_cancel_handler(
            sale=sale, items=[_make_sale_item()], stock=_make_stock(quantity=45)
        )
        # The terminal sells from another location since the sale
        handler.movement_repo.filter_by.return_value = [
            Movement(
                product_id=100,
                quantity=-5,
                type=MovementType.OUT,
                location_id=4,
                reference_type="sale",
                reference_id=1,
            )
        ]

        handler._handle(POSCancelSaleCommand(sale_id=1))

        handler.movement_repo.filter_by.assert_called_once_with(
            reference_type="sale", reference_id=1
        )
        handler.stock_repo.first_for_update.assert_called_once_with(
            product_id=100, location_id=4
        )

    def test_cancel_creates_the_stock_row_if_the_location_has_none(self):
        from src.pos.sales.app.commands import POSCancelSaleCommand

        sale = _make_sale(status=SaleStatus.CONFIRMED, terminal_id=TERMINAL.id)
        handler = _build_cancel_handler(sale=sale, items=[_make_sale_item()])
        handler.stock_repo.first_for_update.return_value = None

        handler._handle(POSCancelSaleCommand(sale_id=1))

        created = handler.stock_repo.create.call_args.args[0]
        assert (created.product_id, created.quantity) == (100, 5)
        assert created.location_id == LOCATION_ID

    def test_cancel_sale_not_found(self):
        from src.pos.sales.app.commands import POSCancelSaleCommand

        handler = _build_cancel_handler()
        handler.sale_repo.get_by_id.return_value = None

        with pytest.raises(NotFoundError):
            handler._handle(POSCancelSaleCommand(sale_id=999))

    def test_cancel_confirmed_propagates_error(self):
        from src.pos.sales.app.commands import POSCancelSaleCommand

        sale = _make_sale(status=SaleStatus.CONFIRMED)
        items = [_make_sale_item()]
        stock = _make_stock(quantity=45)

        handler = _build_cancel_handler(sale=sale, items=items, stock=stock)
        handler.movement_repo.create.side_effect = RuntimeError("DB error")

        with pytest.raises(RuntimeError, match="DB error"):
            handler._handle(POSCancelSaleCommand(sale_id=1))

    def test_cancel_publishes_event_with_pos_source(self):
        from src.pos.sales.app.commands import POSCancelSaleCommand
        from src.sales.domain.events import SaleCancelled

        sale = _make_sale(status=SaleStatus.CONFIRMED)
        items = [_make_sale_item()]
        stock = _make_stock(quantity=45)

        handler = _build_cancel_handler(sale=sale, items=items, stock=stock)
        handler._handle(POSCancelSaleCommand(sale_id=1))

        handler.event_publisher.publish.assert_called_once()
        published_event = handler.event_publisher.publish.call_args[0][0]
        assert isinstance(published_event, SaleCancelled)
        assert published_event.source == "pos"
        assert published_event.was_confirmed is True

    def test_cancel_draft_publishes_event_with_pos_source(self):
        from src.pos.sales.app.commands import POSCancelSaleCommand
        from src.sales.domain.events import SaleCancelled

        sale = _make_sale(status=SaleStatus.DRAFT)

        handler = _build_cancel_handler(sale=sale)
        handler._handle(POSCancelSaleCommand(sale_id=1))

        handler.event_publisher.publish.assert_called_once()
        published_event = handler.event_publisher.publish.call_args[0][0]
        assert isinstance(published_event, SaleCancelled)
        assert published_event.source == "pos"
        assert published_event.was_confirmed is False


# === Event Handler Guard Tests ===


class TestEventHandlerGuards:
    def test_sale_confirmed_pos_source_skips_inventory(self):
        from src.inventory.infra.event_handlers import handle_sale_confirmed
        from src.sales.domain.events import SaleConfirmed

        event = SaleConfirmed(
            aggregate_id=1,
            sale_id=1,
            customer_id=10,
            items=[{"product_id": 100, "quantity": 5}],
            total=Decimal("1000.0"),
            source="pos",
        )

        handle_sale_confirmed(event)

    def test_sale_cancelled_pos_source_skips_inventory(self):
        from src.inventory.infra.event_handlers import handle_sale_cancelled
        from src.sales.domain.events import SaleCancelled

        event = SaleCancelled(
            aggregate_id=1,
            sale_id=1,
            customer_id=10,
            items=[{"product_id": 100, "quantity": 5}],
            reason="test",
            was_confirmed=True,
            source="pos",
        )

        handle_sale_cancelled(event)

    def test_sale_confirmed_admin_source_processes_normally(self, monkeypatch):
        import src
        from src.inventory.infra.event_handlers import handle_sale_confirmed
        from src.sales.domain.events import SaleConfirmed

        # Reaching the scope proves the handler didn't skip the event
        monkeypatch.setattr(src, "wireup_container", None)

        event = SaleConfirmed(
            aggregate_id=1,
            sale_id=1,
            customer_id=10,
            items=[{"product_id": 100, "quantity": 5}],
            total=Decimal("1000.0"),
            source="admin",
        )

        with pytest.raises(RuntimeError, match="wireup container is not initialized"):
            handle_sale_confirmed(event)

    def test_sale_confirmed_default_source_is_admin(self):
        from src.sales.domain.events import SaleConfirmed

        event = SaleConfirmed(aggregate_id=1, sale_id=1)
        assert event.source == "admin"

    def test_sale_cancelled_default_source_is_admin(self):
        from src.sales.domain.events import SaleCancelled

        event = SaleCancelled(aggregate_id=1, sale_id=1)
        assert event.source == "admin"
