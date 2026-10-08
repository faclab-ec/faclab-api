from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.pos.sales.app.commands.override_price import (
    OverrideItemPriceCommand,
    OverrideItemPriceCommandHandler,
)
from src.sales.domain.entities import Sale, SaleItem, SaleStatus
from src.sales.domain.exceptions import InvalidSaleStatusError
from src.shared.domain.exceptions import NotFoundError, ValidationError
from src.shared.domain.tax import TaxCode


def _make_sale(**overrides) -> Sale:
    defaults: dict[str, Any] = {
        "id": 1,
        "customer_id": 10,
        "status": SaleStatus.DRAFT,
        "subtotal": Decimal("0"),
        "total": Decimal("0"),
    }
    defaults.update(overrides)
    return Sale(**defaults)


def _make_item(**overrides) -> SaleItem:
    defaults: dict[str, Any] = {
        "id": 5,
        "sale_id": 1,
        "product_id": 100,
        "quantity": 2,
        "unit_price": Decimal("50"),
        "discount": Decimal("0"),
        "tax_code": TaxCode.VAT_12,
        "tax_amount": Decimal("12"),
    }
    defaults.update(overrides)
    return SaleItem(**defaults)


def _build_handler(sale=None, item=None, items=None):
    handler = OverrideItemPriceCommandHandler.__new__(OverrideItemPriceCommandHandler)
    handler.sale_repo = MagicMock()
    handler.sale_item_repo = MagicMock()

    if sale is not None:
        handler.sale_repo.get_by_id.return_value = sale
        handler.sale_repo.update.return_value = sale
    if item is not None:
        handler.sale_item_repo.get_by_id.return_value = item
        handler.sale_item_repo.update.return_value = item
    if items is not None:
        handler.sale_item_repo.filter_by.return_value = items

    return handler


class TestOverrideItemPriceCommandHandler:
    def test_override_price_happy_path(self):
        sale = _make_sale()
        item = _make_item()
        handler = _build_handler(sale=sale, item=item, items=[item])

        result = handler._handle(
            OverrideItemPriceCommand(
                sale_id=1,
                item_id=5,
                new_price=Decimal("75"),
                reason="Customer negotiation",
            )
        )

        assert item.unit_price == Decimal("75")
        assert item.price_override == Decimal("75")
        assert item.override_reason == "Customer negotiation"
        assert result["unit_price"] == Decimal("75")
        assert result["price_override"] == Decimal("75")
        assert result["override_reason"] == "Customer negotiation"
        handler.sale_item_repo.update.assert_called_once_with(item)
        handler.sale_repo.update.assert_called_once()

    def test_override_recalculates_tax_amount(self):
        sale = _make_sale()
        item = _make_item(
            quantity=1, unit_price=Decimal("100"), tax_code=TaxCode.VAT_12
        )
        handler = _build_handler(sale=sale, item=item, items=[item])

        handler._handle(
            OverrideItemPriceCommand(
                sale_id=1,
                item_id=5,
                new_price=Decimal("200"),
                reason="Premium upgrade",
            )
        )

        # subtotal = 200 * 1 = 200, tax = 200 * 12 / 100 = 24
        assert item.tax_amount == Decimal("24")

    def test_override_recalculates_sale_totals(self):
        sale = _make_sale()
        item = _make_item(
            quantity=1, unit_price=Decimal("100"), tax_code=TaxCode.VAT_12
        )
        handler = _build_handler(sale=sale, item=item, items=[item])

        handler._handle(
            OverrideItemPriceCommand(
                sale_id=1,
                item_id=5,
                new_price=Decimal("200"),
                reason="Premium upgrade",
            )
        )

        assert sale.subtotal == Decimal("200")
        assert sale.tax == Decimal("24")
        assert sale.total == Decimal("224")

    def test_reject_if_not_draft(self):
        sale = _make_sale(status=SaleStatus.CONFIRMED)
        handler = _build_handler(sale=sale)

        with pytest.raises(InvalidSaleStatusError):
            handler._handle(
                OverrideItemPriceCommand(
                    sale_id=1,
                    item_id=5,
                    new_price=Decimal("75"),
                    reason="Test",
                )
            )

        handler.sale_repo.update.assert_not_called()

    def test_item_not_found(self):
        sale = _make_sale()
        handler = _build_handler(sale=sale)
        handler.sale_item_repo.get_by_id.return_value = None

        with pytest.raises(NotFoundError):
            handler._handle(
                OverrideItemPriceCommand(
                    sale_id=1,
                    item_id=999,
                    new_price=Decimal("75"),
                    reason="Test",
                )
            )

    def test_item_does_not_belong_to_sale(self):
        sale = _make_sale()
        item = _make_item(sale_id=99)
        handler = _build_handler(sale=sale, item=item)

        with pytest.raises(ValidationError):
            handler._handle(
                OverrideItemPriceCommand(
                    sale_id=1,
                    item_id=5,
                    new_price=Decimal("75"),
                    reason="Test",
                )
            )

    def test_sale_not_found(self):
        handler = _build_handler()
        handler.sale_repo.get_by_id.return_value = None

        with pytest.raises(NotFoundError):
            handler._handle(
                OverrideItemPriceCommand(
                    sale_id=999,
                    item_id=5,
                    new_price=Decimal("75"),
                    reason="Test",
                )
            )

    def test_invalid_price_zero(self):
        sale = _make_sale()
        handler = _build_handler(sale=sale)

        with pytest.raises(ValidationError):
            handler._handle(
                OverrideItemPriceCommand(
                    sale_id=1,
                    item_id=5,
                    new_price=Decimal("0"),
                    reason="Test",
                )
            )

    def test_invalid_price_negative(self):
        sale = _make_sale()
        handler = _build_handler(sale=sale)

        with pytest.raises(ValidationError):
            handler._handle(
                OverrideItemPriceCommand(
                    sale_id=1,
                    item_id=5,
                    new_price=Decimal("-10"),
                    reason="Test",
                )
            )
