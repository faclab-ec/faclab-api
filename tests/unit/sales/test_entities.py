from datetime import datetime
from decimal import Decimal

import pytest

from src.sales.domain.entities import (
    InvoiceStatus,
    Payment,
    PaymentMethod,
    PaymentStatus,
    Sale,
    SaleItem,
    SaleStatus,
)
from src.sales.domain.exceptions import (
    CreditNoteRequiredError,
    InsufficientPaymentError,
    InvalidSaleStatusError,
    InvoiceInProgressError,
    PaymentExceedsBalanceError,
    SaleNotParkedError,
    SaleNotPayableError,
)
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
    sale.settle([])
    sale.confirm()
    assert sale.status == SaleStatus.CONFIRMED
    assert sale.sale_date is not None


def test_sale_confirm_requires_it_paid():
    sale = Sale(customer_id=1, status=SaleStatus.DRAFT, total=Decimal("10"))
    with pytest.raises(InsufficientPaymentError):
        sale.confirm()
    assert sale.status == SaleStatus.DRAFT


def _payment(amount: str, method=PaymentMethod.CASH, **kwargs) -> Payment:
    return Payment(sale_id=1, amount=Decimal(amount), payment_method=method, **kwargs)


def test_settle_applies_payments_in_order_and_cash_gives_change():
    sale = Sale(id=1, total=Decimal("24.15"))
    card = _payment("10", PaymentMethod.CREDIT_CARD)
    cash = _payment("20")

    sale.settle([card, cash])

    assert (card.amount, card.change) == (Decimal("10"), Decimal("0"))
    assert (cash.amount, cash.amount_tendered, cash.change) == (
        Decimal("14.15"),
        Decimal("20"),
        Decimal("5.85"),
    )
    assert sale.payment_status == PaymentStatus.PAID


def test_settle_fails_when_payments_dont_cover_the_total():
    sale = Sale(id=1, total=Decimal("24.15"))
    with pytest.raises(InsufficientPaymentError):
        sale.settle([_payment("24.14")])
    assert sale.payment_status == PaymentStatus.PENDING


@pytest.mark.parametrize(
    "method",
    [
        PaymentMethod.CREDIT_CARD,
        PaymentMethod.DEBIT_CARD,
        PaymentMethod.TRANSFER,
        PaymentMethod.OTHER,
    ],
)
def test_only_cash_exceeds_what_is_owed(method):
    sale = Sale(id=1, total=Decimal("24.15"))
    with pytest.raises(PaymentExceedsBalanceError):
        sale.settle([_payment("25", method)])


def test_a_payment_after_the_total_is_covered_is_rejected():
    sale = Sale(id=1, total=Decimal("10"))
    with pytest.raises(PaymentExceedsBalanceError):
        sale.settle([_payment("10"), _payment("5")])


def test_settle_applies_again_what_an_earlier_settle_applied():
    """A draft paid, then its items changed: the change is recomputed"""
    cash = _payment("50")
    Sale(id=1, total=Decimal("40")).settle([cash])
    assert cash.change == Decimal("10")

    Sale(id=1, total=Decimal("45")).settle([cash])

    assert (cash.amount, cash.amount_tendered, cash.change) == (
        Decimal("45"),
        Decimal("50"),
        Decimal("5"),
    )


def test_what_is_handed_over_is_rounded_to_the_cent():
    payment = _payment("10.005")
    assert payment.amount_tendered == Decimal("10.01")


def test_take_payment_applies_what_is_still_owed():
    sale = Sale(id=1, total=Decimal("30"))
    previous = [_payment("10", PaymentMethod.TRANSFER)]
    cash = _payment("25")

    sale.take_payment(cash, previous)

    assert (cash.amount, cash.change) == (Decimal("20"), Decimal("5"))
    assert sale.payment_status == PaymentStatus.PAID


def test_take_payment_keeps_a_partial_payment():
    sale = Sale(id=1, total=Decimal("30"))
    sale.take_payment(_payment("10", PaymentMethod.TRANSFER), [])
    assert sale.payment_status == PaymentStatus.PARTIAL


@pytest.mark.parametrize("status", [SaleStatus.CANCELLED, SaleStatus.INVOICED])
def test_cancelled_or_invoiced_sales_take_no_payments(status):
    sale = Sale(id=1, status=status, total=Decimal("30"))
    with pytest.raises(SaleNotPayableError):
        sale.take_payment(_payment("10"), [])


def test_a_paid_sale_takes_no_more_payments():
    sale = Sale(id=1, status=SaleStatus.CONFIRMED, total=Decimal("30"))
    with pytest.raises(PaymentExceedsBalanceError):
        sale.take_payment(_payment("5"), [_payment("30")])


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


def test_sale_cancel_from_invoiced_requires_a_credit_note():
    """Una venta facturada se anula con nota de crédito (S4.5)"""
    sale = Sale(customer_id=1, status=SaleStatus.INVOICED)
    with pytest.raises(CreditNoteRequiredError):
        sale.cancel()
    assert sale.status == SaleStatus.INVOICED


def test_sale_cancel_from_cancelled_fails():
    sale = Sale(customer_id=1, status=SaleStatus.CANCELLED)
    with pytest.raises(InvalidSaleStatusError):
        sale.cancel()


def test_sale_cancel_while_its_invoice_is_pending_fails():
    sale = Sale(
        customer_id=1, status=SaleStatus.CONFIRMED, invoice_status=InvoiceStatus.PENDING
    )
    with pytest.raises(InvoiceInProgressError):
        sale.cancel()
    assert sale.status == SaleStatus.CONFIRMED


def test_sale_cancel_after_its_invoice_was_rejected():
    sale = Sale(
        customer_id=1,
        status=SaleStatus.CONFIRMED,
        invoice_status=InvoiceStatus.REJECTED,
    )
    sale.cancel()
    assert sale.status == SaleStatus.CANCELLED


def test_a_sale_sent_to_invoicing_awaits_its_invoice():
    sale = Sale(customer_id=1, status=SaleStatus.CONFIRMED)
    sale.await_invoice()
    assert sale.invoice_status == InvoiceStatus.PENDING


def test_a_draft_does_not_await_an_invoice():
    with pytest.raises(InvalidSaleStatusError):
        Sale(customer_id=1, status=SaleStatus.DRAFT).await_invoice()


def test_invoicing_the_sale_authorizes_its_invoice():
    sale = Sale(
        customer_id=1, status=SaleStatus.CONFIRMED, invoice_status=InvoiceStatus.PENDING
    )
    sale.invoice("inv-1")
    assert (sale.status, sale.invoice_status, sale.invoice_id) == (
        SaleStatus.INVOICED,
        InvoiceStatus.AUTHORIZED,
        "inv-1",
    )


def test_a_rejected_invoice_keeps_its_id_and_reason():
    sale = Sale(
        customer_id=1, status=SaleStatus.CONFIRMED, invoice_status=InvoiceStatus.PENDING
    )

    assert sale.reject_invoice("inv-1", "ERROR SECUENCIAL REGISTRADO") is True

    assert (sale.invoice_status, sale.invoice_id, sale.invoice_rejection_reason) == (
        InvoiceStatus.REJECTED,
        "inv-1",
        "ERROR SECUENCIAL REGISTRADO",
    )


def test_a_resend_clears_the_reason_and_ignores_the_old_rejection_again():
    sale = Sale(
        customer_id=1, status=SaleStatus.CONFIRMED, invoice_status=InvoiceStatus.PENDING
    )
    sale.reject_invoice("inv-1", "ERROR SECUENCIAL REGISTRADO")

    sale.await_invoice()
    assert (sale.invoice_status, sale.invoice_rejection_reason) == (
        InvoiceStatus.PENDING,
        None,
    )
    # The rejection of inv-1 delivered again doesn't undo the resend
    assert sale.reject_invoice("inv-1", "ERROR SECUENCIAL REGISTRADO") is False
    assert sale.invoice_status == InvoiceStatus.PENDING
    # The new invoice can be rejected too
    assert sale.reject_invoice("inv-2", "OTRO ERROR") is True
    assert (sale.invoice_id, sale.invoice_rejection_reason) == ("inv-2", "OTRO ERROR")


def test_an_authorized_invoice_clears_the_last_rejection():
    sale = Sale(
        customer_id=1,
        status=SaleStatus.CONFIRMED,
        invoice_status=InvoiceStatus.PENDING,
        invoice_id="inv-1",
    )

    sale.invoice("inv-2")

    assert (sale.invoice_id, sale.invoice_rejection_reason) == ("inv-2", None)


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
