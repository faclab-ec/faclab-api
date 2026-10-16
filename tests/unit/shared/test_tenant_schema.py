"""Every business table belongs to a tenant (S2.3). Walks `Base.metadata` with
every model loaded, so a new table that forgets its tenant fails here."""

import pytest
from sqlalchemy import ForeignKeyConstraint, Table, UniqueConstraint

from src.shared.infra.database import Base
from tests.sqlite import load_all_models

load_all_models()

# Platform tables: no tenant at all
PLATFORM_TABLES = {"tenants", "users", "login_failures"}
# They carry their tenant, but auth, provisioning and the outbox relay read them
# across tenants, so the base repository doesn't filter them
CROSS_TENANT_TABLES = {"memberships", "auth_sessions", "outbox_messages"}
# Relations the database keeps within one tenant: (table, column)
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
    assert len(BUSINESS_TABLES) == 31


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


def test_the_main_relations_use_composite_foreign_keys():
    composite = {
        (constraint.table.name, constraint.column_keys[1])
        for table in TABLES.values()
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and constraint.column_keys[0] == "tenant_id"
        and len(constraint.column_keys) == 2
    }

    assert composite == COMPOSITE_FOREIGN_KEYS
