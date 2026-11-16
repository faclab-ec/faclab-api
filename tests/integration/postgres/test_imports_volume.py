"""Volume of a bulk import (S5.8): a synthetic file of IMPORT_VOLUME_ROWS
products (1,000 by default, so the suite stays quick) is validated and then
imported by the worker, measuring both steps.

The measurement of 10,000 products documented in docs/imports-guide.md:

    make test-integration args="-k volume -s" IMPORT_VOLUME_ROWS=10000
"""

import os
import time

from sqlalchemy import text

from src.auth.domain.entities import Role
from src.imports.infra.runner import run_imports
from tests.integration.postgres.api import Api, unit_id

ROWS = int(os.environ.get("IMPORT_VOLUME_ROWS", "1000"))
# A generous bound, to catch a regression (one query per row in the validation,
# a lookup that loads the catalog per row), not to time the machine
MAX_SECONDS_PER_ROW = 0.05


def _file(rows: int) -> bytes:
    lines = ["sku,nombre,categoria,unidad,codigo_barras,precio_compra,precio_venta,iva"]
    lines += [
        f"VOL-{i:06d},Artículo {i},Categoría {i % 25},und,786{i:010d},"
        f"{i % 90 + 1}.25,{i % 90 + 2}.50,15"
        for i in range(rows)
    ]
    return ("\n".join(lines) + "\n").encode()


def test_a_large_file_is_validated_and_imported_in_a_measured_time(
    client, auth_headers, pg_engine
):
    api = Api(client, auth_headers(Role.ADMIN, full_name="Ana Pérez"))
    unit_id(api)
    content = _file(ROWS)

    start = time.perf_counter()
    job = api.post(
        "/api/admin/imports",
        files={"file": ("volumen.csv", content, "text/csv")},
        data={"kind": "PRODUCTS", "mode": "SKIP"},
    )
    validated = time.perf_counter() - start
    assert job["status"] == "VALIDATED", job
    assert job["planned"]["create"] == ROWS

    api.post(f"/api/admin/imports/{job['id']}/confirm")
    start = time.perf_counter()
    while run_imports(budget_seconds=600):
        pass
    imported = time.perf_counter() - start

    done = api.get(f"/api/admin/imports/{job['id']}")
    print(
        f"\n{ROWS} products ({len(content) / 1024:.0f} KiB): validated in "
        f"{validated:.1f}s, imported in {imported:.1f}s "
        f"({ROWS / imported:.0f} rows/s)"
    )
    assert done["status"] == "COMPLETED", done
    assert done["done"]["create"] == ROWS
    with pg_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM products")).scalar_one() == ROWS
        assert conn.execute(text("SELECT count(*) FROM categories")).scalar_one() == 25
    assert validated < ROWS * MAX_SECONDS_PER_ROW
    assert imported < ROWS * MAX_SECONDS_PER_ROW
