from abc import abstractmethod
from decimal import Decimal

from src.receivables.domain.entities import (
    CustomerPayment,
    Receivable,
    ReceivableApplication,
)
from src.shared.app.repositories import Repository


class ReceivableRepository(Repository[Receivable]):
    @abstractmethod
    def first_for_update(self, **kwargs) -> Receivable | None:
        """Like first(), locking the row until the transaction ends"""

    @abstractmethod
    def open_for_update(self, customer_id: int) -> list[Receivable]:
        """The customer's open receivables, locked in id order: a payment on
        account holds them while it lowers their balances"""

    @abstractmethod
    def outstanding(self, customer_id: int) -> Decimal:
        """What the customer owes: the balance of its open receivables"""


class ReceivableApplicationRepository(Repository[ReceivableApplication]):
    pass


class CustomerPaymentRepository(Repository[CustomerPayment]):
    pass
