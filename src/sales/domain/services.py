"""Cálculo de IVA con descuento global, compartido por ventas, devoluciones y recibos"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import NamedTuple

from src.shared.domain.money import allocate, round_money
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


class SaleLine(NamedTuple):
    """Una línea de la venta a precisión completa"""

    gross: Decimal  # cantidad × precio unitario
    tax_code: TaxCode
    subtotal: Decimal  # después del descuento de la línea
    tax_amount: Decimal  # IVA de la línea, antes del descuento global


@dataclass(frozen=True)
class InvoiceLine:
    """Montos de una línea tal como van en el detalle de la factura del SRI"""

    discount: Decimal  # descuento de la línea más su parte del descuento global
    taxable_base: Decimal  # precioTotalSinImpuesto y baseImponible
    tax: Decimal  # valor del IVA


def invoice_lines(
    lines: Sequence[SaleLine], subtotal: Decimal, discount: Decimal, tax: Decimal
) -> list[InvoiceLine]:
    """Reparte los totales de la venta entre sus líneas para la factura del SRI.

    La factura no tiene descuento global: cada detalle lleva su parte en
    `descuento`, y su base imponible e IVA ya descontados. Las bases suman
    exactamente `subtotal - discount` y el IVA de cada código suma lo mismo que
    en `tax_breakdown`, así que el importe total de la factura es el de la venta.
    """
    bases = allocate(subtotal - discount, [line.subtotal for line in lines])

    breakdown = tax_breakdown(
        ((line.tax_code, line.subtotal, line.tax_amount) for line in lines),
        discount_factor(subtotal, discount),
    )
    code_taxes = {code: code_tax for code, (_, code_tax) in breakdown.items()}
    # Las líneas se guardan con 6 decimales: si al recalcular el IVA se aleja
    # un centavo del de la venta, la diferencia va al grupo con más IVA
    drift = tax - sum(code_taxes.values(), Decimal("0"))
    if drift and code_taxes:
        largest = max(code_taxes, key=lambda code: code_taxes[code])
        code_taxes[largest] += drift

    taxes = [Decimal("0")] * len(lines)
    for code, code_tax in code_taxes.items():
        indexes = [i for i, line in enumerate(lines) if line.tax_code == code]
        shares = allocate(code_tax, [lines[i].tax_amount for i in indexes])
        for i, share in zip(indexes, shares, strict=True):
            taxes[i] = share

    return [
        InvoiceLine(
            discount=max(round_money(line.gross) - base, Decimal("0")),
            taxable_base=base,
            tax=line_tax,
        )
        for line, base, line_tax in zip(lines, bases, taxes, strict=True)
    ]
