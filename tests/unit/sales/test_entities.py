from datetime import datetime
from decimal import Decimal

import pytest

from src.sales.domain.entities import (
    Payment,
    PaymentMethod,
    PaymentStatus,
    Sale,
    SaleItem,
    SaleStatus,
)
from src.sales.domain.exceptions import InvalidSaleStatusError, SaleNotParkedError
from src.shared.domain.exceptions import ValidationError


def test_sale_item_subtotal_calculation():
    """Test que el subtotal se calcula correctamente"""
    item = SaleItem(
        sale_id=1,
        product_id=1,
        quantity=10,
        unit_price=Decimal("100.00"),
        discount=Decimal("10"),  # 10%
    )
    # Subtotal = (10 * 100) - (1000 * 10/100) = 1000 - 100 = 900
    assert item.subtotal == Decimal("900.00")


def test_sale_item_subtotal_no_discount():
    """Test subtotal sin descuento"""
    item = SaleItem(
        sale_id=1,
        product_id=1,
        quantity=5,
        unit_price=Decimal("50.00"),
        discount=Decimal("0"),
    )
    assert item.subtotal == Decimal("250.00")


def test_sale_confirm_changes_status():
    """Test que confirmar una venta cambia su estado"""
    sale = Sale(customer_id=1, status=SaleStatus.DRAFT)
    sale.confirm()
    assert sale.status == SaleStatus.CONFIRMED
    assert sale.sale_date is not None


def test_sale_confirm_only_draft():
    """Test que solo se pueden confirmar ventas en DRAFT"""
    sale = Sale(customer_id=1, status=SaleStatus.CONFIRMED)
    with pytest.raises(InvalidSaleStatusError):
        sale.confirm()


def test_sale_cancel_from_draft():
    """Test cancelar una venta en DRAFT"""
    sale = Sale(customer_id=1, status=SaleStatus.DRAFT)
    sale.cancel()
    assert sale.status == SaleStatus.CANCELLED


def test_sale_cancel_from_confirmed():
    """Test cancelar una venta confirmada"""
    sale = Sale(customer_id=1, status=SaleStatus.CONFIRMED)
    sale.cancel()
    assert sale.status == SaleStatus.CANCELLED


def test_sale_cancel_from_invoiced_fails():
    """Test que no se pueden cancelar ventas facturadas"""
    sale = Sale(customer_id=1, status=SaleStatus.INVOICED)
    with pytest.raises(InvalidSaleStatusError):
        sale.cancel()


def test_sale_invoice_only_confirmed():
    """Test que solo se pueden facturar ventas confirmadas"""
    sale = Sale(customer_id=1, status=SaleStatus.CONFIRMED)
    sale.invoice()
    assert sale.status == SaleStatus.INVOICED


def test_sale_invoice_draft_fails():
    """Test que no se pueden facturar ventas en DRAFT"""
    sale = Sale(customer_id=1, status=SaleStatus.DRAFT)
    with pytest.raises(InvalidSaleStatusError):
        sale.invoice()


def test_sale_update_payment_status_pending():
    """Test actualizar estado de pago a PENDING"""
    sale = Sale(customer_id=1, total=Decimal("1000"))
    sale.update_payment_status(Decimal("0"))
    assert sale.payment_status == PaymentStatus.PENDING


def test_sale_update_payment_status_partial():
    """Test actualizar estado de pago a PARTIAL"""
    sale = Sale(customer_id=1, total=Decimal("1000"))
    sale.update_payment_status(Decimal("500"))
    assert sale.payment_status == PaymentStatus.PARTIAL


def test_sale_update_payment_status_paid():
    """Test actualizar estado de pago a PAID"""
    sale = Sale(customer_id=1, total=Decimal("1000"))
    sale.update_payment_status(Decimal("1000"))
    assert sale.payment_status == PaymentStatus.PAID


def test_sale_update_payment_status_overpaid():
    """Test actualizar estado de pago cuando se paga de más"""
    sale = Sale(customer_id=1, total=Decimal("1000"))
    sale.update_payment_status(Decimal("1500"))
    assert sale.payment_status == PaymentStatus.PAID


def test_sale_update_payment_status_paid_ignores_sub_cent_difference():
    """El front cobra con float: 30.596999… cubre un total de 30.597"""
    sale = Sale(customer_id=1, total=Decimal("30.597"))
    sale.update_payment_status(Decimal("30.596999999999998"))
    assert sale.payment_status == PaymentStatus.PAID


def test_sale_is_covered_by_compares_to_the_cent():
    sale = Sale(customer_id=1, total=Decimal("100.8"))
    assert sale.is_covered_by(Decimal("100.79999999999998"))
    assert not sale.is_covered_by(Decimal("100.79"))


def test_sale_apply_discount_sets_type_and_value():
    sale = Sale(customer_id=1)
    sale.apply_discount("PERCENTAGE", Decimal("10"))
    assert sale.discount_type == "PERCENTAGE"
    assert sale.discount_value == Decimal("10")


def test_sale_apply_discount_only_draft():
    sale = Sale(customer_id=1, status=SaleStatus.CONFIRMED)
    with pytest.raises(InvalidSaleStatusError):
        sale.apply_discount("AMOUNT", Decimal("5"))


@pytest.mark.parametrize(
    ("discount_type", "value"),
    [
        ("FIXED", Decimal("5")),
        ("AMOUNT", Decimal("-1")),
        ("PERCENTAGE", Decimal("101")),
    ],
)
def test_sale_apply_discount_rejects_invalid_values(discount_type, value):
    sale = Sale(customer_id=1)
    with pytest.raises(ValidationError):
        sale.apply_discount(discount_type, value)
    assert sale.discount_type is None


def test_payment_validates_positive_amount():
    """Test que Payment valida que el monto sea positivo"""
    with pytest.raises(ValueError, match="Payment amount must be positive"):
        Payment(
            sale_id=1,
            amount=Decimal("-100"),
            payment_method=PaymentMethod.CASH,
        )


def test_payment_validates_zero_amount():
    """Test que Payment no acepta monto cero"""
    with pytest.raises(ValueError, match="Payment amount must be positive"):
        Payment(
            sale_id=1,
            amount=Decimal("0"),
            payment_method=PaymentMethod.CASH,
        )


def test_payment_sets_default_date():
    """Test que Payment establece fecha por defecto"""
    payment = Payment(
        sale_id=1,
        amount=Decimal("100"),
        payment_method=PaymentMethod.CASH,
    )
    assert payment.payment_date is not None
    assert isinstance(payment.payment_date, datetime)


# === Park / Resume Tests ===


def test_park_sale_from_draft():
    """Test que se puede aparcar una venta en DRAFT"""
    sale = Sale(id=1, customer_id=1, status=SaleStatus.DRAFT)
    sale.park(reason="Cliente olvidó billetera")
    assert sale.parked_at is not None
    assert isinstance(sale.parked_at, datetime)
    assert sale.park_reason == "Cliente olvidó billetera"
    assert sale.status == SaleStatus.DRAFT


def test_park_sale_without_reason():
    """Test que se puede aparcar sin razón"""
    sale = Sale(id=1, customer_id=1, status=SaleStatus.DRAFT)
    sale.park()
    assert sale.parked_at is not None
    assert sale.park_reason is None


def test_park_sale_from_confirmed_raises():
    """Test que no se puede aparcar una venta confirmada"""
    sale = Sale(id=1, customer_id=1, status=SaleStatus.CONFIRMED)
    with pytest.raises(InvalidSaleStatusError):
        sale.park()


def test_park_sale_from_cancelled_raises():
    """Test que no se puede aparcar una venta cancelada"""
    sale = Sale(id=1, customer_id=1, status=SaleStatus.CANCELLED)
    with pytest.raises(InvalidSaleStatusError):
        sale.park()


def test_resume_parked_sale():
    """Test que se puede retomar una venta aparcada"""
    sale = Sale(id=1, customer_id=1, status=SaleStatus.DRAFT)
    sale.park(reason="Test")
    assert sale.parked_at is not None

    sale.resume()
    assert sale.parked_at is None
    assert sale.park_reason is None
    assert sale.status == SaleStatus.DRAFT


def test_resume_non_parked_sale_raises():
    """Test que no se puede retomar una venta que no está aparcada"""
    sale = Sale(id=1, customer_id=1, status=SaleStatus.DRAFT)
    with pytest.raises(SaleNotParkedError):
        sale.resume()
