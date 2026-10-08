from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.pos.sales.app.commands.apply_discount import (
    ApplySaleDiscountCommand,
    ApplySaleDiscountCommandHandler,
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
        "sale_id": 1,
        "product_id": 100,
        "quantity": 1,
        "unit_price": Decimal("100"),
        "discount": Decimal("0"),
        "tax_code": TaxCode.VAT_12,
        "tax_amount": Decimal("12"),
    }
    defaults.update(overrides)
    return SaleItem(**defaults)


def _build_handler(sale=None, items=None):
    handler = ApplySaleDiscountCommandHandler.__new__(ApplySaleDiscountCommandHandler)
    handler.sale_repo = MagicMock()
    handler.sale_item_repo = MagicMock()

    if sale is not None:
        handler.sale_repo.get_by_id.return_value = sale
        handler.sale_repo.update.return_value = sale
    if items is not None:
        handler.sale_item_repo.filter_by.return_value = items

    return handler


class TestApplySaleDiscountCommandHandler:
    def test_apply_percentage_discount(self):
        sale = _make_sale()
        items = [_make_item()]
        handler = _build_handler(sale=sale, items=items)

        result = handler._handle(
            ApplySaleDiscountCommand(
                sale_id=1,
                discount_type="PERCENTAGE",
                discount_value=Decimal("10"),
            )
        )

        assert result["discount_type"] == "PERCENTAGE"
        assert result["discount_value"] == Decimal("10")
        assert result["discount"] == Decimal("10")  # 10% of 100
        assert result["tax"] == Decimal("10.8")  # 12% of the discounted base (90)
        assert result["total"] == Decimal("100.8")  # 100 - 10 + 10.8
        handler.sale_repo.update.assert_called_once()

    def test_apply_amount_discount(self):
        sale = _make_sale()
        items = [_make_item()]
        handler = _build_handler(sale=sale, items=items)

        result = handler._handle(
            ApplySaleDiscountCommand(
                sale_id=1,
                discount_type="AMOUNT",
                discount_value=Decimal("25"),
            )
        )

        assert result["discount_type"] == "AMOUNT"
        assert result["discount"] == Decimal("25")
        assert result["tax"] == Decimal("9")  # 12% of the discounted base (75)
        assert result["total"] == Decimal("84")  # 100 - 25 + 9

    def test_reject_if_not_draft(self):
        sale = _make_sale(status=SaleStatus.CONFIRMED)
        handler = _build_handler(sale=sale, items=[])

        with pytest.raises(InvalidSaleStatusError):
            handler._handle(
                ApplySaleDiscountCommand(
                    sale_id=1,
                    discount_type="PERCENTAGE",
                    discount_value=Decimal("10"),
                )
            )

        handler.sale_repo.update.assert_not_called()

    def test_sale_not_found(self):
        handler = _build_handler()
        handler.sale_repo.get_by_id.return_value = None

        with pytest.raises(NotFoundError):
            handler._handle(
                ApplySaleDiscountCommand(
                    sale_id=999,
                    discount_type="PERCENTAGE",
                    discount_value=Decimal("10"),
                )
            )

    def test_invalid_discount_type(self):
        sale = _make_sale()
        handler = _build_handler(sale=sale, items=[])

        with pytest.raises(ValidationError):
            handler._handle(
                ApplySaleDiscountCommand(
                    sale_id=1,
                    discount_type="INVALID",
                    discount_value=Decimal("10"),
                )
            )

    def test_percentage_over_100_raises(self):
        sale = _make_sale()
        handler = _build_handler(sale=sale, items=[])

        with pytest.raises(ValidationError):
            handler._handle(
                ApplySaleDiscountCommand(
                    sale_id=1,
                    discount_type="PERCENTAGE",
                    discount_value=Decimal("150"),
                )
            )
