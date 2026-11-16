"""Uploading, confirming and running an import (S5.8)"""

from unittest.mock import MagicMock

import pytest

from src.imports.app.commands.create_import import (
    CreateImportCommand,
    CreateImportCommandHandler,
)
from src.imports.app.commands.run_import import (
    ConfirmImportCommand,
    ConfirmImportCommandHandler,
    FailImportCommand,
    FailImportCommandHandler,
    RunImportBatchCommand,
    RunImportBatchCommandHandler,
)
from src.imports.app.kinds import KindImporters
from src.imports.app.kinds.partners import CustomerImporter, SupplierImporter
from src.imports.app.kinds.presentations import PresentationImporter
from src.imports.app.kinds.prices import PriceImporter
from src.imports.app.kinds.products import ProductImporter
from src.imports.app.kinds.stock import StockImporter
from src.imports.app.queries.imports import (
    GetImportErrorsQuery,
    GetImportErrorsQueryHandler,
    GetImportTemplateQuery,
    GetImportTemplateQueryHandler,
    GetImportTemplatesQuery,
    GetImportTemplatesQueryHandler,
)
from src.imports.domain.entities import (
    ImportJob,
    ImportKind,
    ImportMode,
    ImportRowAction,
    ImportStatus,
)
from src.imports.domain.exceptions import (
    ImportFileInvalidError,
    ImportNotConfirmableError,
    ImportRowFailedError,
)
from src.shared.app.audit import AuditAction
from src.shared.domain.exceptions import AlreadyExistsError
from src.shared.domain.tenant import TenantContext, TenantSource
from tests.audit import FakeAuditTrail
from tests.conftest import TEST_TENANT_ID
from tests.imports import (
    FakeImportLookups,
    InMemoryImportJobs,
    InMemoryImportRows,
    product,
)

HEADER = ["sku", "nombre", "unidad", "precio_venta"]
USER = TenantContext(
    TEST_TENANT_ID, TenantSource.REQUEST, user_id=7, branch_id=2, user_name="Ana Pérez"
)


class _World:
    def __init__(self, lookups: FakeImportLookups | None = None):
        self.lookups = lookups or FakeImportLookups()
        self.create_product = MagicMock()
        self.create_product.handle.side_effect = self._created
        self.next_id = 1000
        self.importers = KindImporters(
            ProductImporter(
                self.lookups, self.create_product, MagicMock(), MagicMock()
            ),
            PresentationImporter(self.lookups, MagicMock(), MagicMock()),
            PriceImporter(self.lookups, MagicMock(), MagicMock()),
            CustomerImporter(self.lookups, MagicMock(), MagicMock(), MagicMock()),
            SupplierImporter(self.lookups, MagicMock(), MagicMock()),
            StockImporter(self.lookups, MagicMock(), MagicMock(), MagicMock()),
        )
        self.jobs = InMemoryImportJobs()
        self.rows = InMemoryImportRows()
        self.audit = FakeAuditTrail()

    def _created(self, command) -> dict:
        self.next_id += 1
        # The product is there for the next batch's plan
        self.lookups.product_list.append(product(self.next_id, command.sku))
        return {"id": self.next_id}

    def upload(
        self, *lines: list, header=HEADER, mode=ImportMode.SKIP, max_rows=100
    ) -> dict:
        handler = CreateImportCommandHandler(self.jobs, self.rows, self.importers, USER)
        return handler.handle(
            CreateImportCommand(
                kind=ImportKind.PRODUCTS,
                mode=mode,
                file_name="productos.csv",
                file_size=120,
                header=header,
                rows=[(n, cells) for n, cells in enumerate(lines, start=2)],
                max_rows=max_rows,
            )
        )

    def confirm(self, job_id: int) -> dict:
        return ConfirmImportCommandHandler(self.jobs, self.audit).handle(
            ConfirmImportCommand(job_id=job_id, request_id="req-1")
        )

    def run(self, job_id: int, batch_size: int = 2) -> dict:
        return RunImportBatchCommandHandler(
            self.jobs, self.rows, self.importers
        ).handle(RunImportBatchCommand(job_id=job_id, batch_size=batch_size))


def _line(sku: str, price: str = "1.50") -> list:
    return [sku, f"Producto {sku}", "und", price]


# -- upload ------------------------------------------------------------------


def test_a_valid_file_is_stored_validated_without_importing_anything():
    world = _World()

    job = world.upload(_line("A-1"), _line("A-2"), ["", None, " ", None])

    assert job["status"] == ImportStatus.VALIDATED
    assert job["total_rows"] == 2
    assert job["planned"][ImportRowAction.CREATE.value] == 2
    assert (job["user_id"], job["user_name"], job["branch_id"]) == (7, "Ana Pérez", 2)
    world.create_product.handle.assert_not_called()
    stored = sorted(world.rows.rows.values(), key=lambda r: r.row_number)
    assert [(r.job_id, r.row_number, r.action) for r in stored] == [
        (job["id"], 2, ImportRowAction.CREATE),
        (job["id"], 3, ImportRowAction.CREATE),
    ]
    assert stored[0].data == {
        "sku": "A-1",
        "nombre": "Producto A-1",
        "unidad": "und",
        "precio_venta": "1.50",
    }


def test_a_file_with_errors_is_invalid_with_the_detail_by_row():
    world = _World()

    job = world.upload(_line("A-1"), _line("A-2", price="doce"), _line("A-1"))

    assert job["status"] == ImportStatus.INVALID
    assert job["planned"][ImportRowAction.ERROR.value] == 2
    errors = GetImportErrorsQueryHandler(world.jobs, world.rows).handle(
        GetImportErrorsQuery(job_id=job["id"])
    )
    assert errors["header"][:4] == ["fila", "columna", "codigo", "mensaje"]
    assert [line[:3] for line in errors["rows"]] == [
        [3, "precio_venta", "INVALID_VALUE"],
        [4, "sku", "DUPLICATE_IN_FILE"],
    ]
    # The row's cells follow, to fix them in the file
    assert errors["rows"][0][4:9] == ["A-2", "Producto A-2", None, None, "und"]


@pytest.mark.parametrize(
    ("header", "mode", "message"),
    [
        (["sku", "nombre", "precio"], ImportMode.SKIP, "no tiene: precio"),
        (["SKU", "sku"], ImportMode.SKIP, "repetidas: sku"),
        (["nombre", "precio_venta"], ImportMode.UPDATE, "obligatorias: sku"),
        (["sku", "precio_venta"], ImportMode.SKIP, "obligatorias: nombre, unidad"),
    ],
)
def test_a_header_that_doesnt_match_the_template_rejects_the_file(
    header, mode, message
):
    with pytest.raises(ImportFileInvalidError, match=message):
        _World().upload(["A-1", "1"], header=header, mode=mode)


def test_updating_needs_only_the_key_columns():
    lookups = FakeImportLookups(product_list=[product(1, "A-1")])

    job = _World(lookups).upload(
        ["A-1", "2.00"], header=["sku", "precio_venta"], mode=ImportMode.UPDATE
    )

    assert job["status"] == ImportStatus.VALIDATED
    assert job["planned"][ImportRowAction.UPDATE.value] == 1


def test_an_empty_or_too_long_file_is_rejected():
    with pytest.raises(ImportFileInvalidError, match="no tiene filas"):
        _World().upload([None, None, None, None])
    with pytest.raises(ImportFileInvalidError, match="más de 2 filas"):
        _World().upload(_line("A-1"), _line("A-2"), _line("A-3"), max_rows=2)


# -- confirm -------------------------------------------------------------------


def test_only_a_validated_import_is_confirmed_and_it_is_audited():
    world = _World()
    valid = world.upload(_line("A-1"))
    invalid = world.upload(_line("A-1", price="x"))

    confirmed = world.confirm(valid["id"])

    assert confirmed["status"] == ImportStatus.QUEUED
    assert confirmed["request_id"] == "req-1"
    [entry] = world.audit.entries
    assert (entry.action, entry.resource_id) == (
        AuditAction.IMPORT_CONFIRMED,
        valid["id"],
    )
    assert entry.after is not None and entry.after["kind"] == ImportKind.PRODUCTS
    for job_id in (invalid["id"], valid["id"]):
        with pytest.raises(ImportNotConfirmableError):
            world.confirm(job_id)


# -- run -----------------------------------------------------------------------


def test_the_worker_runs_an_import_in_batches_until_it_completes():
    world = _World()
    job = world.upload(_line("A-1"), _line("A-2"), _line("A-3"))
    world.confirm(job["id"])

    first = world.run(job["id"])
    progress = world.jobs.rows[job["id"]]
    second = world.run(job["id"])

    assert first == {"locked": False, "status": "RUNNING", "processed": 2}
    assert (progress.processed_rows, progress.cursor_row) == (2, 3)
    assert second == {"locked": False, "status": "COMPLETED", "processed": 1}
    done = world.jobs.rows[job["id"]]
    assert done.done[ImportRowAction.CREATE.value] == 3
    assert done.started_at is not None and done.finished_at is not None
    assert sorted((r.row_number, r.record_id) for r in world.rows.rows.values()) == [
        (2, 1001),
        (3, 1002),
        (4, 1003),
    ]
    # Run again, nothing happens
    assert world.run(job["id"])["processed"] == 0
    assert world.create_product.handle.call_count == 3


def test_a_batch_another_worker_holds_is_left_alone():
    world = _World()
    job = world.upload(_line("A-1"))
    world.confirm(job["id"])
    world.jobs.locked.add(job["id"])

    assert world.run(job["id"]) == {"locked": True, "status": None, "processed": 0}


def test_a_row_whose_data_changed_since_it_was_validated_stops_the_import():
    world = _World()
    job = world.upload(_line("A-1"), _line("A-2"))
    world.confirm(job["id"])
    # The unit was deleted after the file was validated
    world.lookups.unit_refs = []

    with pytest.raises(ImportRowFailedError) as failed:
        world.run(job["id"])

    assert failed.value.row_number == 2
    assert failed.value.reason == "No existe la unidad und"


def test_a_command_that_rejects_a_row_stops_the_import_at_that_row():
    world = _World()
    job = world.upload(_line("A-1"))
    world.confirm(job["id"])
    world.create_product.handle.side_effect = AlreadyExistsError("SKU taken")

    with pytest.raises(ImportRowFailedError) as failed:
        world.run(job["id"])

    assert (failed.value.row_number, failed.value.reason) == (2, "SKU taken")
    FailImportCommandHandler(world.jobs).handle(
        FailImportCommand(job_id=job["id"], row_number=2, message="SKU taken")
    )
    stopped = world.jobs.rows[job["id"]]
    assert (stopped.status, stopped.failed_row, stopped.failure) == (
        ImportStatus.FAILED,
        2,
        "SKU taken",
    )
    errors = GetImportErrorsQueryHandler(world.jobs, world.rows).handle(
        GetImportErrorsQuery(job_id=job["id"])
    )
    assert errors["rows"] == [[2, None, "IMPORT_ROW_FAILED", "SKU taken"]]


def test_failing_a_finished_import_changes_nothing():
    jobs = InMemoryImportJobs(
        ImportJob(
            kind=ImportKind.STOCK,
            mode=ImportMode.SKIP,
            file_name="s.csv",
            file_size=1,
            status=ImportStatus.COMPLETED,
        )
    )

    FailImportCommandHandler(jobs).handle(FailImportCommand(1, None, "late"))

    assert jobs.rows[1].status == ImportStatus.COMPLETED


# -- templates -------------------------------------------------------------------


def test_every_kind_has_a_template_with_its_key_columns():
    templates = GetImportTemplatesQueryHandler().handle(GetImportTemplatesQuery())

    assert [t["kind"] for t in templates] == list(ImportKind)
    keys = {t["kind"]: [c["name"] for c in t["columns"] if c["key"]] for t in templates}
    assert keys == {
        ImportKind.PRODUCTS: ["sku"],
        ImportKind.PRESENTATIONS: ["sku", "presentacion"],
        ImportKind.PRICES: ["lista", "sku", "presentacion", "cantidad_minima"],
        ImportKind.CUSTOMERS: ["identificacion"],
        ImportKind.SUPPLIERS: ["identificacion"],
        ImportKind.STOCK: ["bodega", "ubicacion", "sku"],
    }
    template = GetImportTemplateQueryHandler().handle(
        GetImportTemplateQuery(kind=ImportKind.STOCK)
    )
    assert template["file_name"] == "plantilla-saldos-iniciales"
    assert template["header"] == [
        "bodega",
        "ubicacion",
        "sku",
        "cantidad",
        "costo_unitario",
    ]
