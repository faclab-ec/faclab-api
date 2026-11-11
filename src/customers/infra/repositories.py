from sqlalchemy.orm import Session
from wireup import injectable

from src.customers.app.repositories import CustomerContactRepository, CustomerRepository
from src.customers.domain.entities import Customer, CustomerContact
from src.customers.domain.exceptions import CustomerTaxIdAlreadyExistsError
from src.customers.infra.mappers import CustomerContactMapper, CustomerMapper
from src.customers.infra.models import CustomerContactModel, CustomerModel
from src.shared.infra.repositories import SqlAlchemyRepository


@injectable(lifetime="scoped", as_type=CustomerRepository)
class SqlAlchemyCustomerRepository(SqlAlchemyRepository[Customer], CustomerRepository):
    __model__ = CustomerModel
    __unique_errors__ = {
        "uq_customers_tenant_tax_id": CustomerTaxIdAlreadyExistsError,
    }

    def __init__(self, session: Session, mapper: CustomerMapper):
        super().__init__(session, mapper)

    def first_for_update(self, **kwargs) -> Customer | None:
        """FOR NO KEY UPDATE (S5.5): a sale being inserted holds FOR KEY SHARE on
        its customer's row (its foreign key). FOR UPDATE would wait for it while
        that sale waits for the stock this one locked, a deadlock; this lock
        still makes two sales on credit of the customer take turns."""
        criteria = [
            getattr(CustomerModel, key) == value for key, value in kwargs.items()
        ]
        model = self._query().filter(*criteria).with_for_update(key_share=True)
        return self.mapper.to_entity(model.first())


@injectable(lifetime="scoped", as_type=CustomerContactRepository)
class SqlAlchemyCustomerContactRepository(
    SqlAlchemyRepository[CustomerContact], CustomerContactRepository
):
    __model__ = CustomerContactModel

    def __init__(self, session: Session, mapper: CustomerContactMapper):
        super().__init__(session, mapper)
