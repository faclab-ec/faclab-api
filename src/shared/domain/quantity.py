"""Cantidades decimales (S5.1).

La base de datos guarda seis decimales (lo que admite `cantidad` en el XML 1.1.0
del SRI) y cada unidad de medida dice cuántos acepta. Un producto sin unidad
solo acepta cantidades enteras.
"""

from decimal import Decimal

from src.shared.domain.exceptions import ValidationError

MAX_QUANTITY_DECIMALS = 6
# Decimales de un producto sin unidad de medida
DEFAULT_QUANTITY_DECIMALS = 0


def decimals_of(quantity: Decimal) -> int:
    """Decimales significativos: 2.50 tiene uno, 3.000000 ninguno"""
    exponent = quantity.normalize().as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0


def format_quantity(quantity: Decimal | int) -> str:
    """La cantidad sin ceros sobrantes ni notación exponencial: 2.5, 10"""
    value = Decimal(quantity)
    if value == value.to_integral_value():
        return str(value.quantize(Decimal(1)))
    return format(value.normalize(), "f")


class QuantityPrecisionError(ValidationError):
    """La cantidad tiene más decimales de los que admite la unidad del producto"""

    error_code = "QUANTITY_PRECISION_EXCEEDED"

    def __init__(self, quantity: Decimal, decimals: int, product_id: int | None = None):
        allowed = (
            "whole numbers"
            if decimals == 0
            else f"at most {decimals} decimal{'s' if decimals > 1 else ''}"
        )
        subject = f"Product {product_id}" if product_id is not None else "This unit"
        super().__init__(
            f"{subject} takes {allowed}: {format_quantity(quantity)} is not allowed"
        )
        self.quantity = quantity
        self.decimals = decimals
        self.product_id = product_id


def ensure_quantity_decimals(
    quantity: Decimal | int, decimals: int, product_id: int | None = None
) -> None:
    """Rechaza una cantidad con más decimales de los que admite su unidad"""
    if decimals_of(Decimal(quantity)) > decimals:
        raise QuantityPrecisionError(Decimal(quantity), decimals, product_id)
