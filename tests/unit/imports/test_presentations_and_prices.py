"""Presentations and price list prices (S5.8)"""

from decimal import Decimal
from unittest.mock import MagicMock

from src.catalog.product.app.commands.presentations import (
    CreateProductPresentationCommand,
    UpdateProductPresentationCommand,
)
from src.imports.app.kinds.presentations import PresentationImporter
from src.imports.app.kinds.prices import PriceImporter
from src.imports.app.lookups import PresentationRef, PriceItemRef, PriceListRef
from src.imports.domain.entities import (
    ImportJob,
    ImportKind,
    ImportMode,
    ImportRowAction,
)
from src.pricing.app.commands.items import (
    CreatePriceListItemCommand,
    UpdatePriceListItemCommand,
)
from tests.imports import METER, FakeImportLookups, base, mocked, product, rows

A = ImportRowAction
JOB = ImportJob(
    id=1,
    kind=ImportKind.PRESENTATIONS,
    mode=ImportMode.UPDATE,
    file_name="f",
    file_size=1,
)


def _box(product_id: int) -> PresentationRef:
    return PresentationRef(
        id=700,
        product_id=product_id,
        name="Caja x100",
        factor=Decimal(100),
        barcode="786100",
        sale_price=Decimal("13.50"),
        purchase_price=None,
        is_base=False,
        is_active=True,
    )


def _catalog() -> FakeImportLookups:
    lookups = FakeImportLookups()
    screw = product(1, "TOR-1")
    cable = product(2, "CAB-1", unit=METER)
    lookups.product_list = [screw, cable]
    lookups.presentation_list = [
        base(screw, "786001"),
        base(cable, unit=METER),
        _box(1),
    ]
    return lookups


def _presentations(lookups: FakeImportLookups) -> PresentationImporter:
    create = MagicMock()
    create.handle.return_value = {"id": 901}
    return PresentationImporter(lookups, create, MagicMock())


def _prices(lookups: FakeImportLookups) -> PriceImporter:
    create = MagicMock()
    create.handle.return_value = {"id": 801}
    return PriceImporter(lookups, create, MagicMock())


# -- presentations -------------------------------------------------------------


def test_a_presentation_is_created_updated_or_rejected():
    plans = _presentations(_catalog()).plan(
        rows(
            {"sku": "TOR-1", "presentacion": "Funda x10", "factor": "10"},
            {"sku": "TOR-1", "presentacion": "caja X100", "precio_venta": "12.00"},
            {"sku": "TOR-1", "presentacion": "Unidad", "factor": "1"},
            {"sku": "NO-1", "presentacion": "Caja", "factor": "5"},
            {"sku": "TOR-1", "presentacion": "Media", "factor": "0.5"},
            {
                "sku": "TOR-1",
                "presentacion": "Paca",
                "factor": "50",
                "codigo_barras": "786001",
            },
            {"sku": "TOR-1", "presentacion": "Bolsa"},
            {"sku": "CAB-1", "presentacion": "Rollo", "factor": "50.5"},
        ),
        ImportMode.UPDATE,
    )

    assert [(p.action, [e.code for e in p.errors]) for p in plans] == [
        (A.CREATE, []),
        (A.UPDATE, []),
        (A.ERROR, ["NOT_ALLOWED"]),  # the base one goes with the product
        (A.ERROR, ["NOT_FOUND"]),
        (A.ERROR, ["INVALID_VALUE"]),  # the unit takes whole numbers
        (A.ERROR, ["ALREADY_IN_USE"]),
        (A.ERROR, ["REQUIRED"]),  # a new one needs its factor
        (A.CREATE, []),  # meters take two decimals
    ]
    assert plans[1].payload["name"] == "Caja x100"
    assert plans[1].payload["factor"] == Decimal(100)
    assert plans[1].payload["sale_price"] == Decimal("12.00")


def test_presentations_are_written_with_the_catalogs_commands():
    importer = _presentations(_catalog())
    plans = importer.plan(
        rows(
            {"sku": "TOR-1", "presentacion": "Funda x10", "factor": "10"},
            {"sku": "TOR-1", "presentacion": "Caja x100", "activo": "NO"},
        ),
        ImportMode.UPDATE,
    )

    importer.execute(JOB, plans)

    assert mocked(importer.create).handle.call_args.args[
        0
    ] == CreateProductPresentationCommand(
        product_id=1, name="Funda x10", factor=Decimal(10)
    )
    update = mocked(importer.update).handle.call_args.args[0]
    assert isinstance(update, UpdateProductPresentationCommand)
    assert (update.presentation_id, update.is_active, update.barcode) == (
        700,
        False,
        "786100",
    )
    assert [p.record_id for p in plans] == [901, 700]


# -- prices --------------------------------------------------------------------


def _price_lookups() -> FakeImportLookups:
    lookups = _catalog()
    lookups.price_list_refs = [
        PriceListRef(1, "General", True),
        PriceListRef(2, "Mayorista", False),
    ]
    lookups.price_item_list = [
        PriceItemRef(40, 2, 700, Decimal("0"), Decimal("12.90")),
    ]
    return lookups


def test_a_price_needs_its_list_product_and_presentation():
    plans = _prices(_price_lookups()).plan(
        rows(
            {"lista": "mayorista", "sku": "TOR-1", "precio": "0.12"},
            {
                "lista": "Mayorista",
                "sku": "TOR-1",
                "presentacion": "Caja x100",
                "precio": "12.50",
            },
            {
                "lista": "Mayorista",
                "sku": "TOR-1",
                "presentacion": "Caja x100",
                "cantidad_minima": "0",
                "precio": "12.90",
            },
            {"lista": "General", "sku": "TOR-1", "precio": "0.10"},
            {
                "lista": "General",
                "sku": "TOR-1",
                "cantidad_minima": "100",
                "precio": "0.10",
            },
            {"lista": "VIP", "sku": "TOR-1", "precio": "1"},
            {
                "lista": "Mayorista",
                "sku": "TOR-1",
                "presentacion": "Paca",
                "precio": "1",
            },
            {
                "lista": "Mayorista",
                "sku": "TOR-1",
                "cantidad_minima": "1.5",
                "precio": "1",
            },
            {"lista": "Mayorista", "sku": "TOR-1", "cantidad_minima": "50"},
        ),
        ImportMode.UPDATE,
    )

    assert [(p.action, [e.code for e in p.errors]) for p in plans] == [
        (A.CREATE, []),
        (A.UPDATE, []),
        (A.ERROR, ["DUPLICATE_IN_FILE"]),
        (A.ERROR, ["NOT_ALLOWED"]),  # the general list only keeps tiers
        (A.CREATE, []),
        (A.ERROR, ["NOT_FOUND"]),
        (A.ERROR, ["NOT_FOUND"]),
        (A.ERROR, ["INVALID_VALUE"]),
        (A.ERROR, ["REQUIRED"]),
    ]
    assert plans[1].target_id == 40


def test_a_price_that_is_already_there_is_unchanged_or_skipped():
    file = rows(
        {
            "lista": "Mayorista",
            "sku": "TOR-1",
            "presentacion": "Caja x100",
            "precio": "12.9",
        }
    )

    [same] = _prices(_price_lookups()).plan(file, ImportMode.UPDATE)
    [skipped] = _prices(_price_lookups()).plan(file, ImportMode.SKIP)

    assert same.action == A.UNCHANGED
    assert skipped.action == A.SKIP


def test_prices_are_written_with_the_pricing_commands():
    importer = _prices(_price_lookups())
    plans = importer.plan(
        rows(
            {
                "lista": "Mayorista",
                "sku": "TOR-1",
                "cantidad_minima": "10",
                "precio": "0.11",
            },
            {
                "lista": "Mayorista",
                "sku": "TOR-1",
                "presentacion": "Caja x100",
                "precio": "12.00",
            },
        ),
        ImportMode.UPDATE,
    )

    importer.execute(JOB, plans)

    assert mocked(importer.create).handle.call_args.args[
        0
    ] == CreatePriceListItemCommand(
        price_list_id=2,
        product_id=1,
        presentation_id=100,
        min_quantity=Decimal(10),
        price=Decimal("0.11"),
    )
    assert mocked(importer.update).handle.call_args.args[
        0
    ] == UpdatePriceListItemCommand(
        price_list_id=2, item_id=40, price=Decimal("12.00"), min_quantity=Decimal(0)
    )
