"""The POS read models query the models directly, so they filter by tenant
themselves: run them against SQLite with a second tenant that reuses ids,
SKUs and dates."""

from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from src.catalog.product.infra.models import CategoryModel, ProductModel
from src.catalog.uom.infra.models import UnitOfMeasureModel
from src.customers.infra.models import CustomerModel
from src.pos.cash.app.queries.get_cash_summary import compute_cash_summary
from src.pos.cash.infra.models import CashMovementModel
from src.pos.refund.infra.models import RefundItemModel, RefundModel, RefundPaymentModel
from src.pos.reports.app.queries.by_payment_method import (
    GetSalesByPaymentMethodQuery,
    GetSalesByPaymentMethodQueryHandler,
)
from src.pos.reports.app.queries.daily_summary import (
    GetDailySummaryQuery,
    GetDailySummaryQueryHandler,
)
from src.pos.reports.app.queries.x_report import GetXReportQuery, GetXReportQueryHandler
from src.pos.reports.app.queries.z_report import GetZReportQuery, GetZReportQueryHandler
from src.pos.sales.app.queries.generate_receipt import (
    GenerateReceiptQuery,
    GenerateReceiptQueryHandler,
)
from src.pos.shift.infra.models import ShiftModel
from src.sales.infra.models import PaymentModel, SaleItemModel, SaleModel
from src.shared.domain.exceptions import NotFoundError
from src.shared.domain.tenant import TenantContext, TenantSource, use_tenant
from src.tenancy.infra.models import TenantModel
from tests.sqlite import sqlite_session

OTHER = TenantContext(UUID("00000000-0000-4000-8000-0000000000b2"), TenantSource.TASK)
DAY = date(2026, 3, 14)

_MODELS = (
    CategoryModel,
    UnitOfMeasureModel,
    ProductModel,
    CustomerModel,
    ShiftModel,
    SaleModel,
    SaleItemModel,
    PaymentModel,
    RefundModel,
    RefundItemModel,
    RefundPaymentModel,
    CashMovementModel,
)


def _sell(session: Session, shift_id: int, sale_id: int, amount: str) -> None:
    """A confirmed cash sale of one unit of product `sale_id`"""
    total = Decimal(amount)
    session.add(ProductModel(id=sale_id, name="Martillo", sku="MAR-01"))
    session.add(CustomerModel(id=sale_id, name="Cliente", tax_id="0912345678"))
    session.add(ShiftModel(id=shift_id, cashier_name=f"Caja {shift_id}"))
    session.flush()
    session.add(
        SaleModel(
            id=sale_id,
            customer_id=sale_id,
            shift_id=shift_id,
            status="CONFIRMED",
            sale_date=datetime(2026, 3, 14, 10),
            subtotal=total,
            total=total,
        )
    )
    session.flush()
    session.add(
        SaleItemModel(sale_id=sale_id, product_id=sale_id, quantity=1, unit_price=total)
    )
    session.add(PaymentModel(sale_id=sale_id, amount=total, payment_method="CASH"))
    session.add(CashMovementModel(shift_id=shift_id, type="IN", amount=Decimal("5")))
    session.commit()


@pytest.fixture
def session() -> Iterator[Session]:
    db = sqlite_session(_MODELS)
    db.add(TenantModel(id=OTHER.tenant_id, ruc="0999999999001", legal_name="B"))
    db.commit()
    _sell(db, shift_id=1, sale_id=1, amount="100")
    with use_tenant(OTHER):
        _sell(db, shift_id=2, sale_id=2, amount="900")
    yield db
    db.close()


def test_the_x_report_only_sees_the_tenants_sales(session):
    report = GetXReportQueryHandler(session).handle(GetXReportQuery(shift_id=1))

    assert report["sales_summary"]["total"] == Decimal("100")
    assert [row["total"] for row in report["payments_by_method"]] == [Decimal("100")]
    assert [row["quantity"] for row in report["items_sold"]] == [1]


def test_another_tenants_shift_is_not_found(session):
    x_handler = GetXReportQueryHandler(session)

    with pytest.raises(NotFoundError):
        x_handler.handle(GetXReportQuery(shift_id=2))
    with pytest.raises(NotFoundError):
        GetZReportQueryHandler(session, x_handler).handle(GetZReportQuery(shift_id=2))


def test_the_cash_summary_of_another_tenants_shift_is_empty(session):
    assert compute_cash_summary(session, 1)["cash_sales"] == Decimal("100")
    assert compute_cash_summary(session, 2) == {
        "cash_sales": 0,
        "cash_refunds": 0,
        "cash_in": 0,
        "cash_out": 0,
    }


def test_daily_reports_only_add_up_the_tenants_sales(session):
    daily = GetDailySummaryQueryHandler(session).handle(GetDailySummaryQuery(date=DAY))
    by_method = GetSalesByPaymentMethodQueryHandler(session).handle(
        GetSalesByPaymentMethodQuery(from_date=DAY, to_date=DAY)
    )

    assert daily["total_sales"] == 1
    assert daily["total_amount"] == Decimal("100")
    assert [row["total_amount"] for row in by_method] == [Decimal("100")]


def test_another_tenants_receipt_is_not_found(session):
    handler = GenerateReceiptQueryHandler(session)

    assert handler.handle(GenerateReceiptQuery(sale_id=1))["total"] == Decimal("100")
    with pytest.raises(NotFoundError):
        handler.handle(GenerateReceiptQuery(sale_id=2))
