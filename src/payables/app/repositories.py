from abc import abstractmethod
from decimal import Decimal

from src.payables.domain.entities import Payable, PayableApplication, SupplierPayment
from src.shared.app.repositories import Repository


class PayableRepository(Repository[Payable]):
    @abstractmethod
    def open_for_update(self, supplier_id: int) -> list[Payable]:
        """The supplier's open payables, locked in id order: a payment or a
        return holds them while it lowers their balances"""

    @abstractmethod
    def outstanding(self, supplier_id: int) -> Decimal:
        """What is owed to the supplier: the balance of its open payables"""


class PayableApplicationRepository(Repository[PayableApplication]):
    pass


class SupplierPaymentRepository(Repository[SupplierPayment]):
    pass
