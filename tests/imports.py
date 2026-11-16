"""In-memory lookups and repositories of the bulk import (S5.8), for unit tests"""

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any, cast
from unittest.mock import MagicMock

from src.catalog.product.domain.entities import Product
from src.customers.domain.entities import Customer
from src.imports.app.lookups import (
    ImportLookups,
    LocationRef,
    PresentationRef,
    PriceItemRef,
    PriceListRef,
    UnitRef,
    WarehouseRef,
    key,
)
from src.imports.app.repositories import ImportJobRepository, ImportRowRepository
from src.imports.domain.entities import (
    ImportJob,
    ImportKind,
    ImportRow,
    ImportRowAction,
    ImportStatus,
)
from src.suppliers.domain.entities import Supplier

UND = UnitRef(1, "und", "Unidad", 0)
METER = UnitRef(2, "m", "Metro", 2)


@dataclass
class FakeImportLookups(ImportLookups):
    """What a tenant has, as plain lists; lookups count the calls"""

    unit_refs: list[UnitRef] = field(default_factory=lambda: [UND, METER])
    category_refs: dict[str, int] = field(default_factory=dict)
    product_list: list[Product] = field(default_factory=list)
    presentation_list: list[PresentationRef] = field(default_factory=list)
    price_list_refs: list[PriceListRef] = field(default_factory=list)
    price_item_list: list[PriceItemRef] = field(default_factory=list)
    customer_list: list[Customer] = field(default_factory=list)
    supplier_list: list[Supplier] = field(default_factory=list)
    warehouse_refs: list[WarehouseRef] = field(default_factory=list)
    location_refs: list[LocationRef] = field(default_factory=list)
    stock_levels: dict[tuple[int, int], Decimal] = field(default_factory=dict)
    calls: int = 0

    def units(self) -> dict[str, UnitRef]:
        self.calls += 1
        return {key(unit.symbol): unit for unit in self.unit_refs}

    def categories(self) -> dict[str, int]:
        self.calls += 1
        return {key(name): id for name, id in self.category_refs.items()}

    def products(self, skus: Iterable[str]) -> dict[str, Product]:
        self.calls += 1
        wanted = set(skus)
        return {p.sku: p for p in self.product_list if p.sku in wanted}

    def presentations(
        self, product_ids: Iterable[int]
    ) -> dict[int, list[PresentationRef]]:
        self.calls += 1
        wanted = set(product_ids)
        found: dict[int, list[PresentationRef]] = {}
        for presentation in self.presentation_list:
            if presentation.product_id in wanted:
                found.setdefault(presentation.product_id, []).append(presentation)
        return found

    def barcodes(self, barcodes: Iterable[str]) -> dict[str, PresentationRef]:
        self.calls += 1
        wanted = set(barcodes)
        return {
            p.barcode: p
            for p in self.presentation_list
            if p.barcode is not None and p.barcode in wanted
        }

    def price_lists(self) -> dict[str, PriceListRef]:
        self.calls += 1
        return {key(ref.name): ref for ref in self.price_list_refs}

    def price_items(
        self, price_list_ids: Iterable[int], product_ids: Iterable[int]
    ) -> dict[tuple[int, int, Decimal], PriceItemRef]:
        self.calls += 1
        lists = set(price_list_ids)
        return {
            (item.price_list_id, item.presentation_id, item.min_quantity): item
            for item in self.price_item_list
            if item.price_list_id in lists
        }

    def customers(self, tax_ids: Iterable[str]) -> dict[str, Customer]:
        self.calls += 1
        wanted = set(tax_ids)
        return {c.tax_id: c for c in self.customer_list if c.tax_id in wanted}

    def suppliers(self, tax_ids: Iterable[str]) -> dict[str, Supplier]:
        self.calls += 1
        wanted = set(tax_ids)
        return {s.tax_id: s for s in self.supplier_list if s.tax_id in wanted}

    def warehouses(self) -> dict[str, WarehouseRef]:
        self.calls += 1
        return {key(ref.code): ref for ref in self.warehouse_refs}

    def locations(
        self, warehouse_ids: Iterable[int]
    ) -> dict[tuple[int, str], LocationRef]:
        self.calls += 1
        wanted = set(warehouse_ids)
        return {
            (ref.warehouse_id, key(ref.code)): ref
            for ref in self.location_refs
            if ref.warehouse_id in wanted
        }

    def stock(self, pairs: Iterable[tuple[int, int]]) -> dict[tuple[int, int], Decimal]:
        self.calls += 1
        return {
            pair: self.stock_levels[pair] for pair in pairs if pair in self.stock_levels
        }


def product(id: int, sku: str, *, unit: UnitRef = UND, **values: Any) -> Product:
    return Product(
        id=id,
        sku=sku,
        name=values.pop("name", f"Producto {sku}"),
        unit_of_measure_id=unit.id,
        sale_price=values.pop("sale_price", Decimal("1.50")),
        **values,
    )


def base(
    product: Product, barcode: str | None = None, unit: UnitRef = UND
) -> PresentationRef:
    return PresentationRef(
        id=product.require_id() * 100,
        product_id=product.require_id(),
        name=unit.name,
        factor=Decimal(1),
        barcode=barcode,
        sale_price=None,
        purchase_price=None,
        is_base=True,
        is_active=True,
    )


def rows(*data: dict[str, str | None], first: int = 2) -> list[ImportRow]:
    """Rows of a file, numbered from line 2 (the header is line 1)"""
    return [
        ImportRow(
            job_id=0,
            row_number=first + i,
            data=dict(cells),
            action=ImportRowAction.CREATE,
        )
        for i, cells in enumerate(data)
    ]


class InMemoryImportJobs(ImportJobRepository):
    def __init__(self, *jobs: ImportJob):
        self.rows: dict[int, ImportJob] = {}
        self.locked: set[int] = set()
        for job in jobs:
            self.create(job)

    def create(self, entity: ImportJob) -> ImportJob:
        entity = replace(entity, id=entity.id or len(self.rows) + 1)
        self.rows[entity.require_id()] = replace(entity)
        return replace(entity)

    def update(self, entity: ImportJob) -> ImportJob:
        self.rows[entity.require_id()] = replace(entity)
        return replace(entity)

    def delete(self, id: int) -> None:
        self.rows.pop(id)

    def get_all(self) -> list[ImportJob]:
        return [replace(job) for job in self.rows.values()]

    def get_by_id(self, id: int) -> ImportJob | None:
        job = self.rows.get(id)
        return replace(job) if job else None

    def get_by_ids(self, ids: Iterable[int]) -> list[ImportJob]:
        return [replace(self.rows[id]) for id in ids if id in self.rows]

    def first(self, **kwargs) -> ImportJob | None:
        raise NotImplementedError

    def filter_by(self, limit=None, offset=None, **kwargs) -> list[ImportJob]:
        raise NotImplementedError

    def count_by(self, **kwargs) -> int:
        raise NotImplementedError

    def filter_by_spec(
        self, spec, order_by=None, desc_order=False, limit=None, offset=None
    ):
        raise NotImplementedError

    def paginate(self, limit=None, offset=None, **kwargs) -> dict:
        raise NotImplementedError

    def paginate_by_spec(
        self, spec, limit=None, offset=None, order_by=None, desc_order=False
    ):
        raise NotImplementedError

    def lock_for_run(self, job_id: int) -> ImportJob | None:
        if job_id in self.locked:
            return None
        return self.get_by_id(job_id)

    def page(
        self,
        kind: ImportKind | None,
        status: ImportStatus | None,
        limit: int,
        offset: int,
    ) -> dict:
        jobs = [
            job
            for job in sorted(self.rows.values(), key=lambda j: -j.require_id())
            if (kind is None or job.kind == kind)
            and (status is None or job.status == status)
        ]
        return {
            "total": len(jobs),
            "limit": limit,
            "offset": offset,
            "items": jobs[offset : offset + limit],
        }


class InMemoryImportRows(ImportRowRepository):
    def __init__(self):
        self.rows: dict[int, ImportRow] = {}

    def add_many(self, rows: Iterable[ImportRow]) -> None:
        for row in rows:
            row_id = len(self.rows) + 1
            self.rows[row_id] = replace(row, id=row_id)

    def after(self, job_id: int, row_number: int, limit: int) -> list[ImportRow]:
        found = sorted(
            (
                row
                for row in self.rows.values()
                if row.job_id == job_id and row.row_number > row_number
            ),
            key=lambda row: row.row_number,
        )
        return [replace(row) for row in found[:limit]]

    def record_results(
        self, results: Iterable[tuple[int, ImportRowAction, int | None]]
    ) -> None:
        for row_id, action, record_id in results:
            self.rows[row_id] = replace(
                self.rows[row_id], action=action, record_id=record_id
            )

    def page(
        self, job_id: int, action: ImportRowAction | None, limit: int, offset: int
    ) -> dict:
        found = [
            row
            for row in sorted(self.rows.values(), key=lambda r: r.row_number)
            if row.job_id == job_id and (action is None or row.action == action)
        ]
        return {
            "total": len(found),
            "limit": limit,
            "offset": offset,
            "items": found[offset : offset + limit],
        }

    def with_errors(self, job_id: int) -> list[ImportRow]:
        return self.page(job_id, ImportRowAction.ERROR, 10**9, 0)["items"]

    def create(self, entity: ImportRow) -> ImportRow:
        raise NotImplementedError

    def update(self, entity: ImportRow) -> ImportRow:
        raise NotImplementedError

    def delete(self, id: int) -> None:
        raise NotImplementedError

    def get_all(self) -> list[ImportRow]:
        return list(self.rows.values())

    def get_by_id(self, id: int) -> ImportRow | None:
        return self.rows.get(id)

    def get_by_ids(self, ids: Iterable[int]) -> list[ImportRow]:
        raise NotImplementedError

    def first(self, **kwargs) -> ImportRow | None:
        raise NotImplementedError

    def filter_by(self, limit=None, offset=None, **kwargs) -> list[ImportRow]:
        raise NotImplementedError

    def count_by(self, **kwargs) -> int:
        raise NotImplementedError

    def filter_by_spec(
        self, spec, order_by=None, desc_order=False, limit=None, offset=None
    ):
        raise NotImplementedError

    def paginate(self, limit=None, offset=None, **kwargs) -> dict:
        raise NotImplementedError

    def paginate_by_spec(
        self, spec, limit=None, offset=None, order_by=None, desc_order=False
    ):
        raise NotImplementedError


def mocked(handler: object) -> MagicMock:
    """A handler an importer was given as a mock, to check its calls"""
    return cast(MagicMock, handler)
