from decimal import Decimal


def discount_factor(subtotal: Decimal, discount: Decimal) -> Decimal:
    """Fracción de la base imponible que queda después del descuento global"""
    if subtotal <= 0:
        return Decimal("1")
    return (subtotal - discount) / subtotal


def recalculate_sale_totals(sale, items) -> None:
    """Recalcula subtotal, descuento, IVA y total de la venta a partir de sus items.

    El descuento global se prorratea sobre la base imponible de cada item, porque el
    IVA se calcula sobre el precio menos los descuentos de la factura (art. 59 LORTI).
    """
    subtotal = sum((item.subtotal for item in items), Decimal("0"))

    if sale.discount_type == "PERCENTAGE":
        discount = subtotal * sale.discount_value / Decimal("100")
    elif sale.discount_type == "AMOUNT":
        discount = min(sale.discount_value, subtotal)
    else:
        discount = Decimal("0")

    item_tax = sum((item.tax_amount for item in items), Decimal("0"))

    sale.subtotal = subtotal
    sale.discount = discount
    sale.tax = item_tax * discount_factor(subtotal, discount)
    sale.total = subtotal - discount + sale.tax
