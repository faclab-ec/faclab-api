from abc import abstractmethod

from src.customers.domain.entities import Customer, CustomerContact
from src.shared.app.repositories import Repository


class CustomerRepository(Repository[Customer]):
    @abstractmethod
    def first_for_update(self, **kwargs) -> Customer | None:
        """Like first(), locking the row until the transaction ends: a sale on
        credit and a payment on account hold it, so its outstanding balance is
        read and changed by one of them at a time (S5.5)"""


class CustomerContactRepository(Repository[CustomerContact]):
    pass
