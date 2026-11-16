"""Customers, suppliers and opening stock (S5.8)"""

from decimal import Decimal
from unittest.mock import MagicMock

from src.customers.app.commands.customer import (
    ChangeCustomerPriceListCommand,
    CreateCustomerCommand,
    UpdateCustomerCommand,
)
from src.customers.domain.entities import Customer
from src.imports.app.kinds.partners import (
    CustomerImporter,
    SupplierImporter,
    tax_id_candidates,
)
from src.imports.app.kinds.stock import StockImporter
from src.imports.app.lookups import LocationRef, PriceListRef, WarehouseRef
from src.imports.domain.entities import (
    ImportJob,
    ImportKind,
    ImportMode,
    ImportRowAction,
)
from src.inventory.adjustment.app.commands.adjustment import (
    AddAdjustmentItemCommand,
    ConfirmAdjustmentCommand,
    CreateAdjustmentCommand,
)
from src.shared.domain.tax import TaxType
from src.suppliers.app.commands.supplier import CreateSupplierCommand
from src.suppliers.domain.entities import Supplier
from tests.imports import METER, FakeImportLookups, mocked, product, rows

A = ImportRowAction
CEDULA = "1710034065"  # a valid cédula
CEDULA_WITH_ZERO = "0102030400"  # province 01: Excel drops its zero
RUC = "1710034065001"


def _job(kind: ImportKind) -> ImportJob:
    return ImportJob(
        id=12,
        kind=kind,
        mode=ImportMode.UPDATE,
        file_name="f.csv",
        file_size=1,
        user_name="Ana Pérez",
    )


def _customers(lookups: FakeImportLookups) -> CustomerImporter:
    create = MagicMock()
    create.handle.return_value = {"id": 300}
    return CustomerImporter(lookups, create, MagicMock(), MagicMock())


def _customer_lookups() -> FakeImportLookups:
    return FakeImportLookups(
        price_list_refs=[PriceListRef(2, "Mayorista", False)],
        customer_list=[
            Customer(
                id=5,
                name="Ferretería Sur",
                tax_id=CEDULA,
                tax_type=TaxType.NATIONAL_ID,
                city="Quito",
                credit_limit=Decimal("500"),
            )
        ],
    )


def test_a_cedula_without_its_leading_zero_gets_it_back():
    assert tax_id_candidates("102030400", TaxType.NATIONAL_ID) == [
        "102030400",
        CEDULA_WITH_ZERO,
    ]
    assert tax_id_candidates("102030400", TaxType.PASSPORT) == ["102030400"]

    [plan] = _customers(FakeImportLookups()).plan(
        rows(
            {
                "tipo_identificacion": "cedula",
                "identificacion": "102030400",
                "nombre": "Ana",
            }
        ),
        ImportMode.SKIP,
    )

    assert plan.ok, plan.errors
    assert plan.payload["tax_id"] == CEDULA_WITH_ZERO


def test_customers_are_validated_like_the_api():
    plans = _customers(_customer_lookups()).plan(
        rows(
            {
                "tipo_identificacion": "RUC",
                "identificacion": "1790000000001",
                "nombre": "X",
            },
            {
                "tipo_identificacion": "CEDULA",
                "identificacion": "1710034066",
                "nombre": "X",
            },
            {
                "tipo_identificacion": "PASAPORTE",
                "identificacion": "AB123",
                "nombre": "X",
                "email": "no-es-correo",
            },
            {"tipo_identificacion": "DNI", "identificacion": "123", "nombre": "X"},
            {"identificacion": "AB999", "nombre": "Sin tipo"},
            {
                "tipo_identificacion": "PASAPORTE",
                "identificacion": "AB124",
                "nombre": "X",
                "lista_precios": "VIP",
            },
            {
                "tipo_identificacion": "PASAPORTE",
                "identificacion": "AB124",
                "nombre": "Y",
            },
        ),
        ImportMode.SKIP,
    )

    assert [[(e.column, e.code) for e in p.errors] for p in plans] == [
        [("identificacion", "INVALID_VALUE")],
        [("identificacion", "INVALID_VALUE")],
        [("email", "INVALID_VALUE")],
        [("tipo_identificacion", "INVALID_VALUE")],
        [("tipo_identificacion", "REQUIRED")],
        [("lista_precios", "NOT_FOUND")],
        [("identificacion", "DUPLICATE_IN_FILE")],
    ]


def test_an_existing_customer_updates_only_what_changed():
    importer = _customers(_customer_lookups())
    plans = importer.plan(
        rows(
            {
                "identificacion": CEDULA,
                "ciudad": "Cuenca",
                "lista_precios": "mayorista",
            },
            {
                "identificacion": CEDULA_WITH_ZERO,
                "tipo_identificacion": "CEDULA",
                "nombre": "Nuevo",
                "lista_precios": "Mayorista",
            },
        ),
        ImportMode.UPDATE,
    )
    assert [p.action for p in plans] == [A.UPDATE, A.CREATE]

    importer.execute(_job(ImportKind.CUSTOMERS), plans)

    update = mocked(importer.update).handle.call_args.args[0]
    assert isinstance(update, UpdateCustomerCommand)
    assert (
        update.id,
        update.name,
        update.city,
        update.credit_limit,
        update.tax_type,
    ) == (
        5,
        "Ferretería Sur",
        "Cuenca",
        Decimal("500"),
        int(TaxType.NATIONAL_ID),
    )
    create = mocked(importer.create).handle.call_args.args[0]
    assert create == CreateCustomerCommand(
        name="Nuevo", tax_id=CEDULA_WITH_ZERO, tax_type=int(TaxType.NATIONAL_ID)
    )
    # The price list goes apart, audited, for both
    assert [
        c.args[0] for c in mocked(importer.change_price_list).handle.call_args_list
    ] == [
        ChangeCustomerPriceListCommand(customer_id=5, price_list_id=2),
        ChangeCustomerPriceListCommand(customer_id=300, price_list_id=2),
    ]


def test_a_customer_whose_only_change_is_the_list_is_not_rewritten():
    importer = _customers(_customer_lookups())
    plans = importer.plan(
        rows({"identificacion": CEDULA, "lista_precios": "Mayorista"}),
        ImportMode.UPDATE,
    )

    importer.execute(_job(ImportKind.CUSTOMERS), plans)

    mocked(importer.update).handle.assert_not_called()
    mocked(importer.change_price_list).handle.assert_called_once()


def test_the_same_customer_again_is_unchanged():
    [plan] = _customers(_customer_lookups()).plan(
        rows({"identificacion": CEDULA, "nombre": "Ferretería Sur", "cupo": "500.00"}),
        ImportMode.UPDATE,
    )

    assert plan.action == A.UNCHANGED


def test_suppliers_are_created_or_updated_by_their_tax_id():
    create = MagicMock()
    create.handle.return_value = {"id": 41}
    lookups = FakeImportLookups(
        supplier_list=[Supplier(id=4, name="Acme", tax_id=RUC, tax_type=TaxType.RUC)]
    )
    importer = SupplierImporter(lookups, create, MagicMock())
    plans = importer.plan(
        rows(
            {
                "tipo_identificacion": "RUC",
                "identificacion": RUC,
                "nombre": "Acme",
                "plazo_dias": "30",
            },
            {
                "tipo_identificacion": "PASAPORTE",
                "identificacion": "P-1",
                "nombre": "Import Co",
                "dias_entrega": "15",
            },
        ),
        ImportMode.UPDATE,
    )

    importer.execute(_job(ImportKind.SUPPLIERS), plans)

    assert [p.action for p in plans] == [A.UPDATE, A.CREATE]
    assert mocked(importer.update).handle.call_args.args[0].payment_terms == 30
    assert create.handle.call_args.args[0] == CreateSupplierCommand(
        name="Import Co",
        tax_id="P-1",
        tax_type=int(TaxType.PASSPORT),
        lead_time_days=15,
    )


# -- opening stock ---------------------------------------------------------------


def _stock_lookups() -> FakeImportLookups:
    return FakeImportLookups(
        product_list=[
            product(1, "TOR-1"),
            product(2, "CAB-1", unit=METER),
            product(3, "SRV-1", is_service=True),
        ],
        warehouse_refs=[WarehouseRef(10, "BOD-001"), WarehouseRef(20, "BOD-002")],
        location_refs=[
            LocationRef(100, 10, "GENERAL"),
            LocationRef(200, 20, "GENERAL"),
        ],
        stock_levels={(1, 100): Decimal(30), (2, 200): Decimal(0)},
    )


def _stock(lookups: FakeImportLookups) -> StockImporter:
    create = MagicMock()
    create.handle.side_effect = lambda command: {"id": 60 + command.warehouse_id}
    return StockImporter(lookups, create, MagicMock(), MagicMock())


def test_an_opening_balance_sets_the_location_to_the_files_quantity():
    file = rows(
        {"bodega": "bod-001", "ubicacion": "general", "sku": "TOR-1", "cantidad": "30"},
        {"bodega": "BOD-001", "ubicacion": "GENERAL", "sku": "TOR-1", "cantidad": "45"}
        | {"costo_unitario": "0.08"},
        {
            "bodega": "BOD-002",
            "ubicacion": "GENERAL",
            "sku": "CAB-1",
            "cantidad": "120.5",
        },
        {"bodega": "BOD-001", "ubicacion": "GENERAL", "sku": "CAB-1", "cantidad": "0"},
    )

    update = _stock(_stock_lookups()).plan(file, ImportMode.UPDATE)
    skip = _stock(_stock_lookups()).plan(file, ImportMode.SKIP)

    assert [p.action for p in update] == [
        A.UNCHANGED,
        A.ERROR,  # the same product and location again
        A.CREATE,
        A.UNCHANGED,
    ]
    assert update[1].errors[0].code == "DUPLICATE_IN_FILE"
    [_, _, created, _] = skip
    assert created.action == A.CREATE


def test_an_opening_balance_over_a_counted_one_updates_or_is_skipped():
    file = rows(
        {"bodega": "BOD-001", "ubicacion": "GENERAL", "sku": "TOR-1", "cantidad": "45"}
    )

    [updated] = _stock(_stock_lookups()).plan(file, ImportMode.UPDATE)
    [skipped] = _stock(_stock_lookups()).plan(file, ImportMode.SKIP)

    assert updated.action == A.UPDATE
    assert skipped.action == A.SKIP


def test_an_opening_balance_needs_a_known_place_a_stocked_product_and_its_decimals():
    plans = _stock(_stock_lookups()).plan(
        rows(
            {
                "bodega": "BOD-9",
                "ubicacion": "GENERAL",
                "sku": "TOR-1",
                "cantidad": "1",
            },
            {
                "bodega": "BOD-001",
                "ubicacion": "PATIO",
                "sku": "TOR-1",
                "cantidad": "1",
            },
            {
                "bodega": "BOD-001",
                "ubicacion": "GENERAL",
                "sku": "SRV-1",
                "cantidad": "1",
            },
            {
                "bodega": "BOD-001",
                "ubicacion": "GENERAL",
                "sku": "TOR-1",
                "cantidad": "1.5",
            },
            {"bodega": "BOD-001", "ubicacion": "GENERAL", "sku": "NO-1"},
        ),
        ImportMode.UPDATE,
    )

    assert [[(e.column, e.code) for e in p.errors] for p in plans] == [
        [("bodega", "NOT_FOUND")],
        [("ubicacion", "NOT_FOUND")],
        [("sku", "NOT_ALLOWED")],
        [("cantidad", "INVALID_VALUE")],
        [("sku", "NOT_FOUND"), ("cantidad", "REQUIRED")],
    ]


def test_opening_balances_go_as_one_confirmed_adjustment_per_warehouse():
    importer = _stock(_stock_lookups())
    plans = importer.plan(
        rows(
            {
                "bodega": "BOD-002",
                "ubicacion": "GENERAL",
                "sku": "CAB-1",
                "cantidad": "120.5",
            },
            {
                "bodega": "BOD-001",
                "ubicacion": "GENERAL",
                "sku": "TOR-1",
                "cantidad": "45",
                "costo_unitario": "0.08",
            },
        ),
        ImportMode.UPDATE,
    )

    importer.execute(_job(ImportKind.STOCK), plans)

    assert [c.args[0] for c in mocked(importer.create).handle.call_args_list] == [
        CreateAdjustmentCommand(
            warehouse_id=10,
            reason="initial_balance",
            notes="Importación #12",
            adjusted_by="Ana Pérez",
        ),
        CreateAdjustmentCommand(
            warehouse_id=20,
            reason="initial_balance",
            notes="Importación #12",
            adjusted_by="Ana Pérez",
        ),
    ]
    assert [c.args[0] for c in mocked(importer.add_item).handle.call_args_list] == [
        AddAdjustmentItemCommand(
            adjustment_id=70,
            product_id=1,
            location_id=100,
            actual_quantity=Decimal(45),
            unit_cost=Decimal("0.08"),
        ),
        AddAdjustmentItemCommand(
            adjustment_id=80,
            product_id=2,
            location_id=200,
            actual_quantity=Decimal("120.5"),
            unit_cost=None,
        ),
    ]
    assert [c.args[0] for c in mocked(importer.confirm).handle.call_args_list] == [
        ConfirmAdjustmentCommand(id=70),
        ConfirmAdjustmentCommand(id=80),
    ]
    assert [p.record_id for p in plans] == [80, 70]
