"""Cálculo de IVA con descuento global, compartido por ventas, devoluciones y recibos"""

from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal

from src.shared.domain.money import round_money
from src.shared.domain.tax import TaxCode

# (código de IVA, subtotal de la línea, IVA de la línea) a precisión completa
TaxedLine = tuple[TaxCode, Decimal, Decimal]


def discount_factor(subtotal: Decimal, discount: Decimal) -> Decimal:
    """Fracción de la base imponible que queda después del descuento global"""
    if subtotal <= 0:
        return Decimal("1")
    return (subtotal - discount) / subtotal


def tax_breakdown(
    lines: Iterable[TaxedLine], factor: Decimal
) -> dict[TaxCode, tuple[Decimal, Decimal]]:
    """Base imponible e IVA por código, ya prorrateado el descuento global.

    El IVA se calcula sobre el precio menos los descuentos de la factura (art. 59
    LORTI), así que cada base y su IVA se multiplican por `factor`. Cada grupo se
    redondea a centavos, como `totalConImpuestos` en la factura electrónica, de
    modo que el IVA de la venta es la suma de los grupos.
    """
    bases: dict[TaxCode, Decimal] = defaultdict(Decimal)
    taxes: dict[TaxCode, Decimal] = defaultdict(Decimal)
    for tax_code, subtotal, tax_amount in lines:
        bases[tax_code] += subtotal
        taxes[tax_code] += tax_amount
    return {
        code: (round_money(bases[code] * factor), round_money(taxes[code] * factor))
        for code in bases
    }
