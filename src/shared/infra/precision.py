"""Centralized numeric precision constants for database columns."""

from collections.abc import Callable
from decimal import Decimal
from typing import Any

from sqlalchemy import Numeric

# Monetary values: prices, costs, subtotals, taxes, totals, amounts, credit limits
# Precision 18 = up to 999,999,999,999.999999 (12 integer digits + 6 decimal
# digits; 12 until S3.3 capped every amount at 999,999.99)
# Scale 6 = 6 decimal places for calculation accuracy
MONEY_PRECISION = 18
MONEY_SCALE = 6
MoneyColumn = Numeric(MONEY_PRECISION, MONEY_SCALE)

# Percentages: discounts, tax rates
# Precision 5 = up to 999.99 (3 integer digits + 2 decimal digits)
# Scale 2 = 2 decimal places (e.g., 12.50%, 33.33%)
PERCENTAGE_PRECISION = 5
PERCENTAGE_SCALE = 2
PercentageColumn = Numeric(PERCENTAGE_PRECISION, PERCENTAGE_SCALE)

# Quantities: stock, movements and the lines of every document (S5.1)
# Precision 18, scale 6 = what the SRI's XML 1.1.0 admits in `cantidad`
# (totalDigits 18, fractionDigits 6). Each unit of measure narrows the
# decimals it accepts (`units_of_measure.decimals`, 0 to 6)
QUANTITY_PRECISION = 18
QUANTITY_SCALE = 6
QuantityColumn = Numeric(QUANTITY_PRECISION, QUANTITY_SCALE)


def base_quantity_of(quantity_column: str) -> Callable[[Any], Decimal]:
    """Default of the `base_quantity` of a line (S5.2) written straight through
    the ORM (the seed, tests): its quantity in the presentation times its
    `unit_factor`. The repositories always write it from the entity."""

    def default(context: Any) -> Decimal:
        params = context.get_current_parameters()
        factor = params.get("unit_factor") or 1
        return Decimal(str(params[quantity_column])) * Decimal(str(factor))

    return default
