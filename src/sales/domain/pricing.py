"""El precio de una línea nueva frente al de su lista (S5.3)"""

from decimal import Decimal

from src.sales.domain.exceptions import (
    OverrideReasonRequiredError,
    ProductWithoutPriceError,
)


def line_price(
    product_id: int,
    list_price: Decimal | None,
    requested: Decimal | None,
    reason: str | None,
) -> tuple[Decimal, bool]:
    """El precio de una línea y si es un override.

    Sin precio pedido, la línea toma el de su lista (el de la lista del cliente,
    la de la sucursal o la general). Uno distinto del de lista es un override:
    exige motivo. Sin precio de lista, cualquier precio pedido vale."""
    if requested is None:
        if list_price is None:
            raise ProductWithoutPriceError(product_id)
        return list_price, False
    unit_price = Decimal(str(requested))
    overridden = list_price is not None and unit_price != list_price
    if overridden and not (reason and reason.strip()):
        raise OverrideReasonRequiredError(product_id)
    return unit_price, overridden
