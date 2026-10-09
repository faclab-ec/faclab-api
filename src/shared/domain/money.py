from collections.abc import Sequence
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def round_money(amount: Decimal) -> Decimal:
    """Redondea a centavos con la mitad hacia arriba, como en la factura.

    Las líneas se guardan con precisión completa; se redondean los totales
    (subtotal, descuento, IVA) de ventas, devoluciones y órdenes de compra.
    """
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def allocate(total: Decimal, weights: Sequence[Decimal]) -> list[Decimal]:
    """Reparte un monto en centavos proporcionalmente a `weights`.

    Cada parte se trunca al centavo y los centavos que sobran van a las partes
    con mayor residuo, así que las partes suman exactamente `total`. Sirve para
    prorratear entre las líneas un total que ya está redondeado.
    """
    if not weights:
        return []
    weight_sum = sum(weights, Decimal("0"))
    if weight_sum == 0:
        weights = [Decimal("1")] * len(weights)
        weight_sum = Decimal(len(weights))

    total_cents = int(round_money(total) / CENT)
    shares = [total_cents * weight / weight_sum for weight in weights]
    cents = [int(share.to_integral_value(rounding=ROUND_FLOOR)) for share in shares]
    by_remainder = sorted(
        range(len(shares)), key=lambda i: shares[i] - cents[i], reverse=True
    )
    for i in by_remainder[: total_cents - sum(cents)]:
        cents[i] += 1
    return [Decimal(c) * CENT for c in cents]
