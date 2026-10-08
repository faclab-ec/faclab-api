from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def round_money(amount: Decimal) -> Decimal:
    """Redondea a centavos con la mitad hacia arriba, como en la factura.

    Las líneas se guardan con precisión completa; se redondean los totales
    (subtotal, descuento, IVA) de ventas, devoluciones y órdenes de compra.
    """
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)
