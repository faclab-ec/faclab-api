"""replace tax_rate with tax_code in products, sale_items and pos_refund_items

Revision ID: c1a2b3d4e5f6
Revises: d4e9a2f1c073
Create Date: 2026-05-22

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1a2b3d4e5f6"
down_revision: str | None = "d4e9a2f1c073"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLES = ("products", "sale_items", "pos_refund_items")

# tax_rate (numeric percentage) -> tax_code (semantic code).
# El 0 histórico se mapea a VAT_0; EXEMPT/NOT_TAXED no son recuperables
# desde el número y se reclasifican manualmente si aplica.
_RATE_TO_CODE = """
    UPDATE {table} SET tax_code = CASE
        WHEN tax_rate = 0 THEN 'VAT_0'
        WHEN tax_rate = 5 THEN 'VAT_5'
        WHEN tax_rate = 8 THEN 'VAT_8_TOURISM'
        WHEN tax_rate = 12 THEN 'VAT_12'
        WHEN tax_rate = 13 THEN 'VAT_13'
        WHEN tax_rate = 14 THEN 'VAT_14'
        WHEN tax_rate = 15 THEN 'VAT_15'
        ELSE 'VAT_15'
    END
"""

# tax_code -> tax_rate (numeric percentage), para el downgrade.
_CODE_TO_RATE = """
    UPDATE {table} SET tax_rate = CASE
        WHEN tax_code = 'VAT_5' THEN 5
        WHEN tax_code = 'VAT_8_TOURISM' THEN 8
        WHEN tax_code = 'VAT_12' THEN 12
        WHEN tax_code = 'VAT_13' THEN 13
        WHEN tax_code = 'VAT_14' THEN 14
        WHEN tax_code = 'VAT_15' THEN 15
        ELSE 0
    END
"""


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column(
                "tax_code",
                sa.String(length=16),
                nullable=False,
                server_default="VAT_15",
            ),
        )
        op.execute(_RATE_TO_CODE.format(table=table))
        op.drop_column(table, "tax_rate")


def downgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column(
                "tax_rate",
                sa.Numeric(precision=5, scale=2),
                nullable=False,
                server_default="0.00",
            ),
        )
        op.execute(_CODE_TO_RATE.format(table=table))
        op.drop_column(table, "tax_code")
