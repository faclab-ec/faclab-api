"""Every business table belongs to a tenant (S2.3) and every reference a route
can fill stays inside it (S2.4). Walks `Base.metadata` with every model loaded, so
a new table or relation that forgets its tenant fails here."""

import pytest
from sqlalchemy import ForeignKeyConstraint, Table, UniqueConstraint

from src.shared.infra.database import Base
from tests.sqlite import load_all_models

load_all_models()

# Platform tables: no tenant at all, or one that may be missing (a dead letter
# keeps the tenant of its message, when the message carried one)
PLATFORM_TABLES = {"tenants", "users", "login_failures", "dead_letters"}
# They carry their tenant, but auth, provisioning and the outbox relay read them
# across tenants, so the base repository doesn't filter them
CROSS_TENANT_TABLES = {
    "memberships",
    "user_branch_access",
    "auth_sessions",
    "outbox_messages",
}
# Relations the database keeps within one tenant: (table, column). PostgreSQL
# checks foreign keys without row-level security, so a single-column key would
# accept another tenant's id
COMPOSITE_FOREIGN_KEYS = {
    ("sales", "customer_id"),
    ("sale_items", "product_id"),
    ("stocks", "product_id"),
    ("stocks", "location_id"),
    ("movements", "product_id"),
    ("movements", "location_id"),
    ("movements", "source_location_id"),
    ("purchase_orders", "supplier_id"),
    ("stock_transfers", "source_location_id"),
    ("stock_transfers", "destination_location_id"),
    ("products", "category_id"),
    ("products", "unit_of_measure_id"),
    ("locations", "warehouse_id"),
    ("lots", "product_id"),
    ("serial_numbers", "product_id"),
    ("serial_numbers", "lot_id"),
    ("serial_numbers", "location_id"),
    ("inventory_adjustments", "warehouse_id"),
    ("adjustment_items", "product_id"),
    ("adjustment_items", "location_id"),
    ("adjustment_items", "lot_id"),
    ("stock_transfer_items", "product_id"),
    ("stock_transfer_items", "lot_id"),
    ("customer_contacts", "customer_id"),
    ("supplier_contacts", "supplier_id"),
    ("supplier_products", "supplier_id"),
    ("supplier_products", "product_id"),
    ("purchase_order_items", "product_id"),
    ("purchase_receipt_items", "location_id"),
    ("warehouses", "branch_id"),
    ("emission_points", "branch_id"),
    ("pos_terminals", "branch_id"),
    ("pos_terminals", "emission_point_id"),
    ("pos_terminals", "default_location_id"),
    ("pos_shifts", "terminal_id"),
    ("pos_shifts", "branch_id"),
    ("sales", "branch_id"),
    ("sales", "emission_point_id"),
    ("sales", "terminal_id"),
    ("pos_refunds", "branch_id"),
    ("pos_refunds", "terminal_id"),
    ("document_sequences", "branch_id"),
}
# Single-column keys no request can point at another tenant: the handler takes
# the value from a parent it already loaded through a tenant-filtered repository
INTERNAL_FOREIGN_KEYS = {
    ("sales", "shift_id"): "the terminal's open shift",
    ("sale_items", "sale_id"): "the sale loaded by id",
    ("payments", "sale_id"): "the sale loaded by id",
    ("pos_cash_movements", "shift_id"): "the shift loaded by id",
    ("pos_refunds", "original_sale_id"): "the sale loaded by id",
    ("pos_refunds", "shift_id"): "the terminal's open shift",
    ("pos_refund_items", "refund_id"): "the refund being created",
    ("pos_refund_items", "original_sale_item_id"): "an item of the loaded sale",
    ("pos_refund_items", "product_id"): "copied from the sale item",
    ("pos_refund_payments", "refund_id"): "the refund loaded by id",
    ("purchase_order_items", "purchase_order_id"): "the order loaded by id",
    ("purchase_receipts", "purchase_order_id"): "the order loaded by id",
    ("purchase_receipt_items", "purchase_receipt_id"): "the receipt being created",
    ("purchase_receipt_items", "purchase_order_item_id"): "an item of the order",
    ("purchase_receipt_items", "product_id"): "copied from the order item",
    ("movement_lot_items", "movement_id"): "the movement being created",
    ("movement_lot_items", "lot_id"): "the lot of the movement's product",
    ("adjustment_items", "adjustment_id"): "the adjustment loaded by id",
    ("stock_transfer_items", "transfer_id"): "the transfer loaded by id",
    ("serial_numbers", "purchase_order_id"): "the order being received",
}

TABLES = Base.metadata.tables
BUSINESS_TABLES = sorted(set(TABLES) - PLATFORM_TABLES - CROSS_TENANT_TABLES)
MODELS = {
    mapper.class_.__tablename__: mapper.class_ for mapper in Base.registry.mappers
}


def _pins_the_tenant(table: Table, column: str) -> bool:
    """`tenant_id`, or a reference to a row of a business table (its parent
    belongs to a single tenant)"""
    if column == "tenant_id":
        return True
    return any(
        fk.column.table.name in BUSINESS_TABLES for fk in table.c[column].foreign_keys
    )


def test_the_classification_covers_every_table():
    assert set(TABLES) >= PLATFORM_TABLES | CROSS_TENANT_TABLES
    assert len(BUSINESS_TABLES) == 36


@pytest.mark.parametrize("name", sorted(set(TABLES) - PLATFORM_TABLES))
def test_every_table_but_the_platform_ones_has_a_tenant(name):
    column = TABLES[name].c.get("tenant_id")

    assert column is not None, f"{name} has no tenant_id"
    assert not column.nullable


@pytest.mark.parametrize("name", BUSINESS_TABLES)
def test_every_business_table_is_tenant_scoped(name):
    to_tenants = [
        fk.target_fullname
        for fk in TABLES[name].c.tenant_id.foreign_keys
        if fk.constraint is not None and len(fk.constraint.columns) == 1
    ]

    assert getattr(MODELS[name], "__tenant_scoped__", False)
    assert to_tenants == ["tenants.id"]


@pytest.mark.parametrize("name", sorted(PLATFORM_TABLES | CROSS_TENANT_TABLES))
def test_platform_and_cross_tenant_tables_are_not_filtered(name):
    assert not getattr(MODELS[name], "__tenant_scoped__", False)


@pytest.mark.parametrize("name", BUSINESS_TABLES)
def test_no_business_table_is_unique_across_tenants(name):
    table = TABLES[name]
    uniques = [
        [column.name for column in constraint.columns]
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    ] + [
        [column.name for column in index.columns]
        for index in table.indexes
        if index.unique
    ]

    for columns in uniques:
        assert any(_pins_the_tenant(table, c) for c in columns), (
            f"{name} is unique on {columns} across tenants"
        )


def _business_foreign_keys() -> list[ForeignKeyConstraint]:
    """Foreign keys from a business table to another one (not to tenants)"""
    return [
        constraint
        for name in BUSINESS_TABLES
        for constraint in TABLES[name].constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and constraint.referred_table.name in BUSINESS_TABLES
    ]


def _is_composite(constraint: ForeignKeyConstraint) -> bool:
    return constraint.column_keys[0] == "tenant_id" and len(constraint.column_keys) == 2


def test_the_main_relations_use_composite_foreign_keys():
    composite = {
        (constraint.table.name, constraint.column_keys[1])
        for constraint in _business_foreign_keys()
        if _is_composite(constraint)
    }

    assert composite == COMPOSITE_FOREIGN_KEYS


def test_every_other_relation_is_internal():
    single = {
        (constraint.table.name, constraint.column_keys[0])
        for constraint in _business_foreign_keys()
        if not _is_composite(constraint)
    }

    assert single == set(INTERNAL_FOREIGN_KEYS), (
        "a single-column key accepts another tenant's id: make it composite "
        "or list it in INTERNAL_FOREIGN_KEYS with the reason"
    )


@pytest.mark.parametrize(
    "constraint",
    [c for c in _business_foreign_keys() if _is_composite(c)],
    ids=lambda c: c.name,
)
def test_composite_foreign_keys_follow_the_convention(constraint):
    table = constraint.table.name
    column = constraint.column_keys[1].removesuffix("_id")
    referred = constraint.referred_table
    targets = {
        tuple(column.name for column in unique.columns)
        for unique in referred.constraints
        if isinstance(unique, UniqueConstraint)
        and unique.name == f"uq_{referred.name}_tenant_id_id"
    }

    assert constraint.name == f"fk_{table}_{column}_tenant"
    assert targets == {("tenant_id", "id")}
    # A plain SET NULL would null tenant_id too: name the column
    assert (constraint.ondelete or "").upper() != "SET NULL"
