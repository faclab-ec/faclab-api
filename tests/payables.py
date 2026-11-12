"""Accounts payable over in-memory repositories, for unit tests (S5.7)"""

from collections.abc import Iterable
from dataclasses import replace
from decimal import Decimal
from typing import Any
from unittest.mock import Mock

from src.payables.app.accounts import SupplierAccounts
from src.payables.app.repositories import (
    PayableApplicationRepository,
    PayableRepository,
    SupplierPaymentRepository,
)
from src.payables.domain.entities import Payable, PayableStatus
from src.suppliers.app.repositories import SupplierRepository
from src.suppliers.domain.entities import Supplier


def _matches(row: Any, filters: dict[str, Any]) -> bool:
    return all(getattr(row, key) == value for key, value in filters.items())


class _InMemory:
    def __init__(self, rows: Iterable[Any] = ()):
        self.rows: dict[int, Any] = {r.require_id(): replace(r) for r in rows}
        self.locked: list[dict[str, Any]] = []

    def create(self, entity):
        entity = replace(entity, id=max(self.rows, default=0) + 1)
        self.rows[entity.require_id()] = replace(entity)
        return replace(entity)

    def update(self, entity):
        self.rows[entity.require_id()] = replace(entity)
        return replace(entity)

    def get_by_id(self, id: int):
        row = self.rows.get(id)
        return replace(row) if row else None

    def get_by_ids(self, ids):
        return [replace(self.rows[i]) for i in ids if i in self.rows]

    def first(self, **kwargs):
        return next(
            (replace(r) for r in self.rows.values() if _matches(r, kwargs)), None
        )

    def filter_by(self, limit=None, offset=None, **kwargs):
        return [replace(r) for r in self.rows.values() if _matches(r, kwargs)]

    def count_by(self, **kwargs) -> int:
        return sum(1 for r in self.rows.values() if _matches(r, kwargs))

    get_all = delete = filter_by_spec = paginate = paginate_by_spec = Mock()


class InMemorySuppliers(_InMemory, SupplierRepository):
    pass


class InMemoryPayables(_InMemory, PayableRepository):
    def open_for_update(self, supplier_id: int) -> list[Payable]:
        self.locked.append({"supplier_id": supplier_id})
        return [
            replace(p)
            for p in sorted(self.rows.values(), key=lambda p: p.id)
            if p.supplier_id == supplier_id and p.status == PayableStatus.OPEN
        ]

    def outstanding(self, supplier_id: int) -> Decimal:
        return sum((p.balance for p in self.open_for_update(supplier_id)), Decimal("0"))


class InMemoryPayableApplications(_InMemory, PayableApplicationRepository):
    pass


class InMemorySupplierPayments(_InMemory, SupplierPaymentRepository):
    pass


def supplier(payment_terms: int | None = 30, id: int = 10) -> Supplier:
    return Supplier(
        id=id,
        name="Distribuidora Andina",
        tax_id="0990000000001",
        payment_terms=payment_terms,
    )


def supplier_accounts(
    *payables: Payable, suppliers: Iterable[Supplier] = ()
) -> tuple[SupplierAccounts, InMemoryPayables, InMemoryPayableApplications]:
    """The real SupplierAccounts over in-memory rows"""
    rows = InMemoryPayables(payables)
    applications = InMemoryPayableApplications()
    accounts = SupplierAccounts(
        InMemorySuppliers(list(suppliers) or [supplier()]), rows, applications
    )
    return accounts, rows, applications
