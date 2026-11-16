"""Bulk import of initial data (S5.8) on PostgreSQL: a file with errors writes
nothing, a confirmed one is imported by the worker with each module's commands
(audited in the uploader's name), and importing it again duplicates nothing."""

import io
from decimal import Decimal

import pytest
from openpyxl import Workbook, load_workbook
from sqlalchemy import Engine, text

from src.auth.domain.entities import Role
from src.imports.infra.runner import run_imports
from tests.integration.postgres.api import (
    Api,
    make_location,
    make_product,
    make_warehouse,
    unit_id,
)

PRODUCTS = (
    "sku;nombre;categoria;unidad;codigo_barras;precio_compra;precio_venta;iva\n"
    "TOR-1;Tornillo 1/2;Tornillería;und;7861000000011;0,08;0,15;15\n"
    "CEM-1;Cemento 50 kg;Construcción;und;7861000000028;6.20;8.10;5\n"
    "CAB-1;Cable 12 AWG;Eléctricos;m;;0.40;0.75;15\n"
)
PRESENTATIONS = (
    "sku,presentacion,factor,codigo_barras,precio_venta\n"
    "TOR-1,Caja x100,100,7861000000035,13.50\n"
    "CAB-1,Rollo 50 m,50,,35.00\n"
)
PRICES = (
    "lista,sku,presentacion,cantidad_minima,precio\n"
    "Mayorista,TOR-1,,,0.12\n"
    "Mayorista,TOR-1,Caja x100,10,11.90\n"
)
CUSTOMERS = (
    "tipo_identificacion,identificacion,nombre,email,cupo,plazo_dias,lista_precios\n"
    "CEDULA,1710034065,Constructora Andes,compras@andes.ec,1500,30,Mayorista\n"
    "PASAPORTE,P-778,Juan Pérez,,,,\n"
)
SUPPLIERS = (
    "tipo_identificacion,identificacion,nombre,plazo_dias,dias_entrega\n"
    "RUC,1710034065001,Distribuidora Norte,45,3\n"
)
STOCK = (
    "bodega,ubicacion,sku,cantidad,costo_unitario\n"
    "BOD-001,GENERAL,TOR-1,1500,0.08\n"
    "BOD-001,GENERAL,CAB-1,250.5,0.40\n"
)


@pytest.fixture
def api(client, auth_headers) -> Api:
    api = Api(client, auth_headers(Role.ADMIN, full_name="Ana Pérez"))
    unit_id(api)
    unit_id(api, "m", "Metro", 2)
    warehouse = make_warehouse(api, "BOD-001")
    make_location(api, warehouse["id"], "GENERAL")
    api.post("/api/admin/price-lists", {"name": "Mayorista"})
    return api


def upload(
    api: Api, kind: str, content: str | bytes, mode: str = "SKIP", name: str = "f.csv"
) -> dict:
    body = content.encode() if isinstance(content, str) else content
    return api.post(
        "/api/admin/imports",
        files={"file": (name, body, "text/csv")},
        data={"kind": kind, "mode": mode},
    )


def run(api: Api, job: dict, batch_size: int = 200) -> dict:
    """Confirms the import and lets the worker run it to the end"""
    api.post(f"/api/admin/imports/{job['id']}/confirm")
    while run_imports(batch_size=batch_size, budget_seconds=60):
        pass
    return api.get(f"/api/admin/imports/{job['id']}")


def product(api: Api, sku: str) -> dict:
    [found] = [p for p in api.get("/api/admin/products") if p["sku"] == sku]
    return found


def counts(engine: Engine, *tables: str) -> dict[str, int]:
    with engine.connect() as conn:
        return {
            table: conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in tables
        }


BUSINESS = (
    "products",
    "product_presentations",
    "categories",
    "customers",
    "suppliers",
    "price_list_items",
    "inventory_adjustments",
    "movements",
    "stocks",
)


def test_a_file_with_errors_writes_nothing_and_answers_by_row(api, pg_engine):
    before = counts(pg_engine, *BUSINESS, "audit_log")
    content = (
        PRODUCTS + "PAL-1;Pala;Herramientas;caja;;5;x;15\n" + "TOR-1;Otra;;und;;;1;15\n"
    )

    job = upload(api, "PRODUCTS", content)

    assert job["status"] == "INVALID"
    assert job["planned"] == {
        "create": 3,
        "update": 0,
        "unchanged": 0,
        "skip": 0,
        "error": 2,
    }
    errors = api.get(f"/api/admin/imports/{job['id']}/rows", params={"action": "ERROR"})
    assert [
        (row["rowNumber"], [(e["column"], e["code"]) for e in row["errors"]])
        for row in errors
    ] == [
        (5, [("precio_venta", "INVALID_VALUE")]),
        (6, [("sku", "DUPLICATE_IN_FILE")]),
    ]
    report = api.client.get(
        f"/api/admin/imports/{job['id']}/errors",
        params={"format": "csv"},
        headers=api.headers,
    )
    assert report.status_code == 200
    assert report.headers["content-disposition"].endswith(
        f'errores-importacion-{job["id"]}.csv"'
    )
    lines = report.content.decode("utf-8-sig").splitlines()
    assert lines[0].startswith("fila,columna,codigo,mensaje,sku,nombre")
    assert lines[1].startswith("5,precio_venta,INVALID_VALUE,")
    error = api.error("POST", f"/api/admin/imports/{job['id']}/confirm", 409)
    assert error["code"] == "IMPORT_NOT_CONFIRMABLE"
    assert counts(pg_engine, *BUSINESS, "audit_log") == before


def test_a_file_that_doesnt_follow_its_template_is_rejected(api):
    error = api.error(
        "POST",
        "/api/admin/imports",
        422,
        files={"file": ("f.csv", b"codigo,nombre\nA,B\n", "text/csv")},
        data={"kind": "PRODUCTS", "mode": "SKIP"},
    )

    assert error["code"] == "IMPORT_FILE_INVALID"
    assert (
        error["message"]
        == "El archivo tiene columnas que la plantilla no tiene: codigo"
    )


def test_initial_data_is_imported_with_each_modules_commands(api, pg_engine):
    products = run(api, upload(api, "PRODUCTS", PRODUCTS))
    assert products["status"] == "COMPLETED", products
    assert products["done"]["create"] == 3
    for kind, content in [
        ("PRESENTATIONS", PRESENTATIONS),
        ("PRICES", PRICES),
        ("CUSTOMERS", CUSTOMERS),
        ("SUPPLIERS", SUPPLIERS),
        ("STOCK", STOCK),
    ]:
        job = run(api, upload(api, kind, content))
        assert job["status"] == "COMPLETED", (kind, job)

    screw = product(api, "TOR-1")
    assert (screw["barcode"], screw["salePrice"], screw["taxCode"]) == (
        "7861000000011",
        0.15,
        "VAT_15",
    )
    assert [p["name"] for p in screw["presentations"]] == ["Unidad", "Caja x100"]
    cement = product(api, "CEM-1")
    assert cement["taxCode"] == "VAT_5"
    [customer] = [
        c for c in api.get("/api/admin/customers") if c["taxId"] == "1710034065"
    ]
    assert (customer["creditLimit"], customer["paymentTerms"]) == (1500.0, 30)
    assert customer["priceListId"] is not None
    with pg_engine.connect() as conn:
        stock = dict(
            conn.execute(
                text(
                    "SELECT p.sku, s.quantity || ' @ ' || s.average_cost FROM stocks s"
                    " JOIN products p ON p.id = s.product_id"
                )
            ).all()
        )
        reasons = conn.execute(
            text("SELECT DISTINCT reason, status FROM inventory_adjustments")
        ).all()
        audited = conn.execute(
            text(
                "SELECT action, actor_name, source, count(*) FROM audit_log"
                " WHERE action IN ('product.created', 'adjustment.confirmed',"
                " 'customer.price_list_changed', 'price_list.item_created')"
                " GROUP BY action, actor_name, source ORDER BY action"
            )
        ).all()
    assert stock == {
        "TOR-1": "1500.000000 @ 0.080000",
        "CAB-1": "250.500000 @ 0.400000",
    }
    assert reasons == [("initial_balance", "confirmed")]
    assert audited == [
        ("adjustment.confirmed", "Ana Pérez", "task", 1),
        ("customer.price_list_changed", "Ana Pérez", "task", 1),
        ("price_list.item_created", "Ana Pérez", "task", 2),
        ("product.created", "Ana Pérez", "task", 3),
    ]


def test_the_worker_audits_with_the_request_that_confirmed_the_import(api, pg_engine):
    job = upload(api, "PRODUCTS", PRODUCTS)
    confirmed = api.client.post(
        f"/api/admin/imports/{job['id']}/confirm",
        headers={**api.headers, "X-Request-Id": "11111111-2222-4333-8444-555555555555"},
    )
    assert confirmed.status_code == 200
    while run_imports(budget_seconds=60):
        pass

    with pg_engine.connect() as conn:
        actions = conn.execute(
            text(
                "SELECT action, count(*) FROM audit_log WHERE request_id = :r"
                " GROUP BY action ORDER BY action"
            ),
            {"r": "11111111-2222-4333-8444-555555555555"},
        ).all()
    assert actions == [("import.confirmed", 1), ("product.created", 3)]


def test_importing_the_same_files_again_duplicates_nothing(api, pg_engine):
    for kind, content in [
        ("PRODUCTS", PRODUCTS),
        ("PRESENTATIONS", PRESENTATIONS),
        ("PRICES", PRICES),
        ("CUSTOMERS", CUSTOMERS),
        ("SUPPLIERS", SUPPLIERS),
        ("STOCK", STOCK),
    ]:
        run(api, upload(api, kind, content))
    before = counts(pg_engine, *BUSINESS)

    for kind, content in [
        ("PRODUCTS", PRODUCTS),
        ("PRESENTATIONS", PRESENTATIONS),
        ("PRICES", PRICES),
        ("CUSTOMERS", CUSTOMERS),
        ("SUPPLIERS", SUPPLIERS),
        ("STOCK", STOCK),
    ]:
        for mode in ("SKIP", "UPDATE"):
            job = upload(api, kind, content, mode=mode)
            assert job["status"] == "VALIDATED", (kind, mode, job)
            assert job["planned"]["create"] == 0, (kind, mode, job)
            assert job["planned"]["update"] == 0, (kind, mode, job)
            assert run(api, job)["status"] == "COMPLETED"

    assert counts(pg_engine, *BUSINESS) == before


def test_updating_changes_only_the_filled_cells(api):
    run(api, upload(api, "PRODUCTS", PRODUCTS))

    job = run(
        api,
        upload(api, "PRODUCTS", "sku,precio_venta\nTOR-1,0.18\nCEM-1,8.10\n", "UPDATE"),
    )

    assert (job["done"]["update"], job["done"]["unchanged"]) == (1, 1)
    screw = product(api, "TOR-1")
    assert (screw["salePrice"], screw["purchasePrice"], screw["name"]) == (
        0.18,
        0.08,
        "Tornillo 1/2",
    )


def test_a_row_that_fails_stops_the_import_and_keeps_the_batches_before(api, pg_engine):
    job = upload(api, "PRODUCTS", PRODUCTS)
    # Someone takes the cement's barcode after the file was validated
    make_product(api, "OTRO-1", barcode="7861000000028")

    stopped = run(api, job, batch_size=1)

    assert stopped["status"] == "FAILED"
    assert stopped["failedRow"] == 3
    assert (
        stopped["failure"]
        == "Otro producto o presentación ya tiene este código de barras"
    )
    assert (stopped["processedRows"], stopped["done"]["create"]) == (1, 1)
    skus = {p["sku"] for p in api.get("/api/admin/products")}
    assert skus == {"OTRO-1", "TOR-1"}


def test_an_xlsx_is_imported_like_a_csv(api):
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(["tipo_identificacion", "identificacion", "nombre", "cupo"])
    # A cédula of province 01 typed as a number: Excel drops its zero
    sheet.append(["CEDULA", 102030400, "Ferretería Azuay", 250.5])
    buffer = io.BytesIO()
    workbook.save(buffer)

    job = run(api, upload(api, "CUSTOMERS", buffer.getvalue(), name="clientes.xlsx"))

    assert job["status"] == "COMPLETED"
    [customer] = api.get("/api/admin/customers")
    assert (customer["taxId"], customer["creditLimit"]) == ("0102030400", 250.5)


def test_templates_are_downloaded_as_xlsx_or_csv(api):
    templates = api.get("/api/admin/imports/templates")
    assert [t["kind"] for t in templates] == [
        "PRODUCTS",
        "PRESENTATIONS",
        "PRICES",
        "CUSTOMERS",
        "SUPPLIERS",
        "STOCK",
    ]

    xlsx = api.client.get("/api/admin/imports/templates/STOCK", headers=api.headers)
    csv = api.client.get(
        "/api/admin/imports/templates/STOCK",
        params={"format": "csv"},
        headers=api.headers,
    )

    workbook = load_workbook(io.BytesIO(xlsx.content))
    assert workbook.sheetnames == ["saldos-iniciales", "Instrucciones"]
    assert csv.content.decode("utf-8-sig").strip() == (
        "bodega,ubicacion,sku,cantidad,costo_unitario"
    )
    assert xlsx.headers["content-disposition"] == (
        'attachment; filename="plantilla-saldos-iniciales.xlsx"'
    )


def test_only_an_admin_imports(client, auth_headers):
    manager = Api(client, auth_headers(Role.MANAGER, username="manager-imports"))

    error = manager.error("GET", "/api/admin/imports", 403)

    assert error["code"] == "PERMISSION_DENIED"


def test_the_cost_of_an_opening_balance_sets_the_average(api, pg_engine):
    run(api, upload(api, "PRODUCTS", PRODUCTS))
    run(
        api,
        upload(
            api,
            "STOCK",
            "bodega,ubicacion,sku,cantidad,costo_unitario\nBOD-001,GENERAL,TOR-1,100,0.10\n",
        ),
    )

    job = run(
        api,
        upload(
            api,
            "STOCK",
            "bodega,ubicacion,sku,cantidad,costo_unitario\nBOD-001,GENERAL,TOR-1,300,0.07\n",
            mode="UPDATE",
        ),
    )

    assert job["done"]["update"] == 1
    with pg_engine.connect() as conn:
        quantity, cost = conn.execute(
            text("SELECT quantity, average_cost FROM stocks")
        ).one()
    # 100 at 0.10 plus 200 at 0.07
    assert (quantity, cost) == (Decimal(300), Decimal("0.080000"))
