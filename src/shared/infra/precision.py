"""Centralized numeric precision constants for database columns."""

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
