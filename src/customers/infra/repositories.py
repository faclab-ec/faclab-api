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


@injectable(lifetime="scoped", as_type=CustomerContactRepository)
class SqlAlchemyCustomerContactRepository(
    SqlAlchemyRepository[CustomerContact], CustomerContactRepository
):
    __model__ = CustomerContactModel

    def __init__(self, session: Session, mapper: CustomerContactMapper):
        super().__init__(session, mapper)
