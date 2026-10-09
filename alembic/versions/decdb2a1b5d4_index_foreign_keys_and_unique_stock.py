"""index foreign keys and make location-less stock unique

Revision ID: decdb2a1b5d4
Revises: c1a2b3d4e5f6
Create Date: 2026-10-08 21:29:19.120827

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "decdb2a1b5d4"
down_revision: str | None = "c1a2b3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# uq_stock_product_location treats NULL locations as distinct, so a product may
# already have several stock rows without location. Fold them into the oldest
# row (adding quantities and reservations) before making them unique.
_MERGE_LOCATIONLESS_STOCK = """
    WITH totals AS (
        SELECT product_id,
               MIN(id) AS keep_id,
               SUM(quantity) AS quantity,
               SUM(reserved_quantity) AS reserved_quantity
        FROM stocks
        WHERE location_id IS NULL
        GROUP BY product_id
        HAVING COUNT(*) > 1
    )
    UPDATE stocks
    SET quantity = totals.quantity,
        reserved_quantity = totals.reserved_quantity
    FROM totals
    WHERE stocks.id = totals.keep_id;

    DELETE FROM stocks AS duplicate
    USING stocks AS kept
    WHERE duplicate.location_id IS NULL
      AND kept.location_id IS NULL
      AND duplicate.product_id = kept.product_id
      AND duplicate.id > kept.id;
"""


def upgrade() -> None:
    op.create_index(
        op.f("ix_adjustment_items_adjustment_id"),
        "adjustment_items",
        ["adjustment_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_customer_contacts_customer_id"),
        "customer_contacts",
        ["customer_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_inventory_adjustments_warehouse_id"),
        "inventory_adjustments",
        ["warehouse_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_movement_lot_items_lot_id"),
        "movement_lot_items",
        ["lot_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_movement_lot_items_movement_id"),
        "movement_lot_items",
        ["movement_id"],
        unique=False,
    )
    op.create_index(op.f("ix_movements_date"), "movements", ["date"], unique=False)
    op.create_index(
        op.f("ix_movements_location_id"), "movements", ["location_id"], unique=False
    )
    op.create_index(
        op.f("ix_movements_product_id"), "movements", ["product_id"], unique=False
    )
    op.create_index(op.f("ix_payments_sale_id"), "payments", ["sale_id"], unique=False)
    op.create_index(
        op.f("ix_pos_cash_movements_shift_id"),
        "pos_cash_movements",
        ["shift_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_pos_refund_items_refund_id"),
        "pos_refund_items",
        ["refund_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_pos_refund_payments_refund_id"),
        "pos_refund_payments",
        ["refund_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_pos_refunds_original_sale_id"),
        "pos_refunds",
        ["original_sale_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_pos_refunds_shift_id"), "pos_refunds", ["shift_id"], unique=False
    )
    op.create_index(
        op.f("ix_products_category_id"), "products", ["category_id"], unique=False
    )
    op.create_index(
        op.f("ix_purchase_order_items_product_id"),
        "purchase_order_items",
        ["product_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_purchase_order_items_purchase_order_id"),
        "purchase_order_items",
        ["purchase_order_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_purchase_orders_supplier_id"),
        "purchase_orders",
        ["supplier_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_purchase_receipt_items_purchase_receipt_id"),
        "purchase_receipt_items",
        ["purchase_receipt_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_purchase_receipts_purchase_order_id"),
        "purchase_receipts",
        ["purchase_order_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sale_items_product_id"), "sale_items", ["product_id"], unique=False
    )
    op.create_index(
        op.f("ix_sale_items_sale_id"), "sale_items", ["sale_id"], unique=False
    )
    op.create_index(
        op.f("ix_sales_customer_id"), "sales", ["customer_id"], unique=False
    )
    op.create_index(op.f("ix_sales_sale_date"), "sales", ["sale_date"], unique=False)
    op.create_index(op.f("ix_sales_shift_id"), "sales", ["shift_id"], unique=False)
    op.create_index(
        op.f("ix_serial_numbers_product_id"),
        "serial_numbers",
        ["product_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_stock_transfer_items_transfer_id"),
        "stock_transfer_items",
        ["transfer_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_stock_transfers_source_location_id"),
        "stock_transfers",
        ["source_location_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_stocks_location_id"), "stocks", ["location_id"], unique=False
    )
    op.execute(_MERGE_LOCATIONLESS_STOCK)
    op.create_index(
        "uq_stock_product_without_location",
        "stocks",
        ["product_id"],
        unique=True,
        postgresql_where=sa.text("location_id IS NULL"),
        sqlite_where=sa.text("location_id IS NULL"),
    )
    op.create_index(
        op.f("ix_supplier_contacts_supplier_id"),
        "supplier_contacts",
        ["supplier_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_supplier_products_product_id"),
        "supplier_products",
        ["product_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_supplier_products_product_id"), table_name="supplier_products"
    )
    op.drop_index(
        op.f("ix_supplier_contacts_supplier_id"), table_name="supplier_contacts"
    )
    op.drop_index(
        "uq_stock_product_without_location",
        table_name="stocks",
        postgresql_where=sa.text("location_id IS NULL"),
        sqlite_where=sa.text("location_id IS NULL"),
    )
    op.drop_index(op.f("ix_stocks_location_id"), table_name="stocks")
    op.drop_index(
        op.f("ix_stock_transfers_source_location_id"), table_name="stock_transfers"
    )
    op.drop_index(
        op.f("ix_stock_transfer_items_transfer_id"), table_name="stock_transfer_items"
    )
    op.drop_index(op.f("ix_serial_numbers_product_id"), table_name="serial_numbers")
    op.drop_index(op.f("ix_sales_shift_id"), table_name="sales")
    op.drop_index(op.f("ix_sales_sale_date"), table_name="sales")
    op.drop_index(op.f("ix_sales_customer_id"), table_name="sales")
    op.drop_index(op.f("ix_sale_items_sale_id"), table_name="sale_items")
    op.drop_index(op.f("ix_sale_items_product_id"), table_name="sale_items")
    op.drop_index(
        op.f("ix_purchase_receipts_purchase_order_id"), table_name="purchase_receipts"
    )
    op.drop_index(
        op.f("ix_purchase_receipt_items_purchase_receipt_id"),
        table_name="purchase_receipt_items",
    )
    op.drop_index(op.f("ix_purchase_orders_supplier_id"), table_name="purchase_orders")
    op.drop_index(
        op.f("ix_purchase_order_items_purchase_order_id"),
        table_name="purchase_order_items",
    )
    op.drop_index(
        op.f("ix_purchase_order_items_product_id"), table_name="purchase_order_items"
    )
    op.drop_index(op.f("ix_products_category_id"), table_name="products")
    op.drop_index(op.f("ix_pos_refunds_shift_id"), table_name="pos_refunds")
    op.drop_index(op.f("ix_pos_refunds_original_sale_id"), table_name="pos_refunds")
    op.drop_index(
        op.f("ix_pos_refund_payments_refund_id"), table_name="pos_refund_payments"
    )
    op.drop_index(op.f("ix_pos_refund_items_refund_id"), table_name="pos_refund_items")
    op.drop_index(
        op.f("ix_pos_cash_movements_shift_id"), table_name="pos_cash_movements"
    )
    op.drop_index(op.f("ix_payments_sale_id"), table_name="payments")
    op.drop_index(op.f("ix_movements_product_id"), table_name="movements")
    op.drop_index(op.f("ix_movements_location_id"), table_name="movements")
    op.drop_index(op.f("ix_movements_date"), table_name="movements")
    op.drop_index(
        op.f("ix_movement_lot_items_movement_id"), table_name="movement_lot_items"
    )
    op.drop_index(op.f("ix_movement_lot_items_lot_id"), table_name="movement_lot_items")
    op.drop_index(
        op.f("ix_inventory_adjustments_warehouse_id"),
        table_name="inventory_adjustments",
    )
    op.drop_index(
        op.f("ix_customer_contacts_customer_id"), table_name="customer_contacts"
    )
    op.drop_index(
        op.f("ix_adjustment_items_adjustment_id"), table_name="adjustment_items"
    )
