"""product construction material code

The SRI subcategory of a construction material (S4.6, G-79; Anexo 23 of the technical
sheet, Res. NAC-DGERCGC24-00000013). Null in every existing product: nobody is
reclassified here, each company picks the code and the 5% rate of its materials.

Revision ID: d8e4f2a1b6c3
Revises: a3d9e1c47b52
Create Date: 2026-11-05 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d8e4f2a1b6c3"
down_revision: str | None = "a3d9e1c47b52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "products",
        sa.Column("construction_material_code", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("products", "construction_material_code")
