from datetime import datetime
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.pos.sales.app.commands.resume_sale import (
    POSResumeSaleCommandHandler,
    ResumeSaleCommand,
)
from src.sales.domain.entities import Sale, SaleStatus
from src.sales.domain.exceptions import SaleNotParkedError
from src.shared.domain.exceptions import NotFoundError


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


def _build_handler(sale=None):
    handler = POSResumeSaleCommandHandler.__new__(POSResumeSaleCommandHandler)
    handler.sale_repo = MagicMock()

    if sale is not None:
        handler.sale_repo.get_by_id.return_value = sale
        handler.sale_repo.update.return_value = sale

    return handler


class TestPOSResumeSaleCommandHandler:
    def test_resume_sale_success(self):
        sale = _make_sale(parked_at=datetime.now(), park_reason="Test")
        handler = _build_handler(sale=sale)

        result = handler._handle(ResumeSaleCommand(sale_id=1))

        assert result["parked_at"] is None
        assert result["park_reason"] is None
        handler.sale_repo.update.assert_called_once()

    def test_resume_sale_not_found(self):
        handler = _build_handler()
        handler.sale_repo.get_by_id.return_value = None

        with pytest.raises(NotFoundError):
            handler._handle(ResumeSaleCommand(sale_id=999))

    def test_resume_non_parked_sale_raises(self):
        sale = _make_sale()  # parked_at is None
        handler = _build_handler(sale=sale)

        with pytest.raises(SaleNotParkedError):
            handler._handle(ResumeSaleCommand(sale_id=1))

        handler.sale_repo.update.assert_not_called()
