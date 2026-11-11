"""The real CustomerCredit over in-memory customers and receivables, for unit
tests (S5.5)"""

from collections.abc import Iterable
from dataclasses import replace
from decimal import Decimal
from typing import Any
from unittest.mock import Mock

from src.customers.app.repositories import CustomerRepository
from src.customers.domain.entities import Customer
from src.receivables.app.credit import CustomerCredit
from src.receivables.app.repositories import (
    CustomerPaymentRepository,
    ReceivableApplicationRepository,
    ReceivableRepository,
)
from src.receivables.domain.entities import (
    Receivable,
    ReceivableApplication,
    ReceivableStatus,
)


def _matches(row: Any, filters: dict[str, Any]) -> bool:
    return all(getattr(row, key) == value for key, value in filters.items())


class _InMemory:
    """create, update, get_by_id, first and count_by over rows kept by id"""

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

    def first_for_update(self, **kwargs):
        self.locked.append(kwargs)
        return self.first(**kwargs)

    def filter_by(self, limit=None, offset=None, **kwargs):
        return [replace(r) for r in self.rows.values() if _matches(r, kwargs)]

    def count_by(self, **kwargs) -> int:
        return sum(1 for r in self.rows.values() if _matches(r, kwargs))

    get_all = delete = filter_by_spec = paginate = paginate_by_spec = Mock()


class InMemoryCustomers(_InMemory, CustomerRepository):
    pass


class InMemoryReceivables(_InMemory, ReceivableRepository):
    def open_for_update(self, customer_id: int) -> list[Receivable]:
        self.locked.append({"customer_id": customer_id})
        return [
            replace(r)
            for r in sorted(self.rows.values(), key=lambda r: r.id)
            if r.customer_id == customer_id and r.status == ReceivableStatus.OPEN
        ]

    def outstanding(self, customer_id: int) -> Decimal:
        return sum(
            (
                r.balance
                for r in self.rows.values()
                if r.customer_id == customer_id and r.status == ReceivableStatus.OPEN
            ),
            Decimal("0"),
        )


class InMemoryApplications(_InMemory, ReceivableApplicationRepository):
    pass


class InMemoryCustomerPayments(_InMemory, CustomerPaymentRepository):
    pass


def credit_customer(
    id: int = 7,
    credit_limit: Decimal | None = Decimal("500"),
    payment_terms: int | None = 30,
    is_active: bool = True,
) -> Customer:
    return Customer(
        id=id,
        name="Constructora Andina",
        tax_id="1790012345001",
        credit_limit=credit_limit,
        payment_terms=payment_terms,
        is_active=is_active,
    )


class InMemoryCredit(CustomerCredit):
    """CustomerCredit over the in-memory repositories, which tests read back"""

    customers: InMemoryCustomers
    receivables: InMemoryReceivables
    applications: InMemoryApplications


def customer_credit(
    customers: Iterable[Customer] = (),
    receivables: Iterable[Receivable] = (),
    applications: Iterable[ReceivableApplication] = (),
    sales: Any = None,
) -> InMemoryCredit:
    """A CustomerCredit whose repositories hold the given rows; its
    `customers`, `receivables` and `applications` are the in-memory ones, so a
    test reads what it wrote (and what it locked). Without customers no sale
    can go on credit, as a tenant that sells none."""
    return InMemoryCredit(
        InMemoryCustomers(customers),
        InMemoryReceivables(receivables),
        InMemoryApplications(applications),
        sales if sales is not None else Mock(),
    )
