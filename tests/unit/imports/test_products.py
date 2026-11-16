"""Products (S5.8): validated against the tenant's catalog, created or updated
with the catalog's commands"""

import time
from decimal import Decimal
from unittest.mock import MagicMock

from src.catalog.product.app.commands.create_category import CreateCategoryCommand
from src.catalog.product.app.commands.create_product import CreateProductCommand
from src.catalog.product.app.commands.update_product import UpdateProductCommand
from src.imports.app.kinds.products import ProductImporter
from src.imports.domain.entities import (
    ImportJob,
    ImportKind,
    ImportMode,
    ImportRowAction,
)
from src.shared.domain.tax import ConstructionMaterialCode, TaxCode
from tests.imports import METER, UND, FakeImportLookups, base, mocked, product, rows

A = ImportRowAction


def _importer(lookups: FakeImportLookups | None = None) -> ProductImporter:
    create = MagicMock()
    create.handle.side_effect = lambda command: {"id": 500}
    update = MagicMock()
    category = MagicMock()
    category.handle.return_value = {"id": 70}
    return ProductImporter(lookups or FakeImportLookups(), create, update, category)


def _row(sku: str, **cells: str) -> dict[str, str | None]:
    return {
        "sku": sku,
        "nombre": f"Producto {sku}",
        "unidad": "und",
        "precio_venta": "1.50",
    } | cells


def _job() -> ImportJob:
    return ImportJob(
        id=9,
        kind=ImportKind.PRODUCTS,
        mode=ImportMode.UPDATE,
        file_name="p.csv",
        file_size=10,
    )


def test_a_new_product_is_planned_with_the_commands_defaults():
    [plan] = _importer().plan(
        rows(_row("A-1", categoria="Tornillería")), ImportMode.SKIP
    )

    assert plan.action == A.CREATE
    assert plan.errors == []
    assert plan.payload["unit_of_measure_id"] == UND.id
    assert plan.payload["tax_code"] == TaxCode.VAT_15
    assert plan.payload["sale_price"] == Decimal("1.50")
    assert plan.payload["new_category"] == "Tornillería"


def test_creating_needs_its_name_unit_and_sale_price():
    [plan] = _importer().plan(rows({"sku": "A-1"}), ImportMode.SKIP)

    assert plan.action == A.ERROR
    assert {(e.column, e.code) for e in plan.errors} == {
        ("nombre", "REQUIRED"),
        ("unidad", "REQUIRED"),
        ("precio_venta", "REQUIRED"),
    }


def test_each_problem_of_a_row_is_reported_with_its_column():
    lookups = FakeImportLookups()
    lookups.product_list = [product(1, "OTRO")]
    lookups.presentation_list = [base(lookups.product_list[0], barcode="786000")]

    plans = _importer(lookups).plan(
        rows(
            _row("A-1", unidad="kg"),
            _row("A-2", precio_venta="doce"),
            _row("A-3", codigo_barras="786000"),
            _row("A-4", material_construccion="F010401", iva="15"),
            _row("A-5", stock_minimo="2.5"),
            _row("A-1"),
        ),
        ImportMode.SKIP,
    )

    assert [(p.row_number, [(e.column, e.code) for e in p.errors]) for p in plans] == [
        (2, [("unidad", "NOT_FOUND")]),
        (3, [("precio_venta", "INVALID_VALUE")]),
        (4, [("codigo_barras", "ALREADY_IN_USE")]),
        (5, [("material_construccion", "NOT_ALLOWED")]),
        (6, [("stock_minimo", "INVALID_VALUE")]),
        (7, [("sku", "DUPLICATE_IN_FILE")]),
    ]
    assert plans[4].errors[0].message == "La unidad und admite solo enteros"
    assert all(p.action == A.ERROR for p in plans)


def test_a_material_with_its_rate_and_a_unit_with_decimals_are_valid():
    [plan, meters] = _importer().plan(
        rows(
            _row("CEM-1", material_construccion="F010401", iva="5"),
            _row("CAB-1", unidad="M", stock_minimo="12,5"),
        ),
        ImportMode.SKIP,
    )

    assert plan.ok and plan.payload["construction_material_code"] == (
        ConstructionMaterialCode.CEMENT
    )
    assert meters.ok and meters.payload["unit_of_measure_id"] == METER.id


def test_an_existing_product_is_skipped_or_updated_with_only_its_filled_cells():
    lookups = FakeImportLookups(category_refs={"Tornillería": 3})
    existing = product(
        1, "A-1", purchase_price=Decimal("0.80"), category_id=3, description="Acero"
    )
    lookups.product_list = [existing]
    lookups.presentation_list = [base(existing, barcode="786001")]
    file = rows({"sku": "A-1", "precio_venta": "2.00"}, {"sku": "A-1"}, first=2)

    [skipped, _] = _importer(lookups).plan(file, ImportMode.SKIP)
    [updated, _] = _importer(lookups).plan(file, ImportMode.UPDATE)

    assert skipped.action == A.SKIP and skipped.target_id == 1
    assert updated.action == A.UPDATE
    assert updated.payload["sale_price"] == Decimal("2.00")
    # What the row leaves empty keeps its value
    assert updated.payload["purchase_price"] == Decimal("0.80")
    assert updated.payload["description"] == "Acero"
    assert updated.payload["barcode"] == "786001"
    assert updated.payload["category_id"] == 3


def test_a_product_with_the_same_values_is_unchanged():
    lookups = FakeImportLookups(category_refs={"Tornillería": 3})
    existing = product(1, "A-1", category_id=3)
    lookups.product_list = [existing]
    lookups.presentation_list = [base(existing, barcode="786001")]

    [plan] = _importer(lookups).plan(
        rows(
            _row(
                "A-1",
                nombre="Producto A-1",
                categoria="tornillería",
                codigo_barras="786001",
                precio_venta="1.5",
            )
        ),
        ImportMode.UPDATE,
    )

    assert plan.action == A.UNCHANGED


def test_executing_creates_each_new_category_once_and_calls_the_catalog():
    importer = _importer()
    plans = importer.plan(
        rows(
            _row("A-1", categoria="Nueva", codigo_barras="786002"),
            _row("A-2", categoria="nueva"),
        ),
        ImportMode.SKIP,
    )

    importer.execute(_job(), plans)

    assert mocked(importer.create_category).handle.call_args_list[0].args == (
        CreateCategoryCommand(name="Nueva"),
    )
    assert mocked(importer.create_category).handle.call_count == 1
    first = mocked(importer.create).handle.call_args_list[0].args[0]
    assert isinstance(first, CreateProductCommand)
    assert (first.sku, first.category_id, first.barcode) == ("A-1", 70, "786002")
    assert [p.record_id for p in plans] == [500, 500]


def test_executing_an_update_sends_the_whole_product():
    lookups = FakeImportLookups()
    existing = product(1, "A-1", is_active=False)
    lookups.product_list = [existing]
    lookups.presentation_list = [base(existing)]
    importer = _importer(lookups)
    plans = importer.plan(rows({"sku": "A-1", "nombre": "Martillo"}), ImportMode.UPDATE)

    importer.execute(_job(), plans)

    command = mocked(importer.update).handle.call_args.args[0]
    assert isinstance(command, UpdateProductCommand)
    assert (command.product_id, command.name, command.is_active) == (
        1,
        "Martillo",
        False,
    )
    assert plans[0].record_id == 1


def test_ten_thousand_rows_are_planned_with_a_handful_of_lookups():
    lookups = FakeImportLookups()
    file = rows(
        *(_row(f"SKU-{i:05d}", codigo_barras=f"786{i:010d}") for i in range(10_000))
    )

    start = time.perf_counter()
    plans = _importer(lookups).plan(file, ImportMode.SKIP)
    elapsed = time.perf_counter() - start

    assert all(plan.action == A.CREATE for plan in plans)
    assert lookups.calls == 5
    assert elapsed < 5, f"planning 10,000 rows took {elapsed:.1f}s"
