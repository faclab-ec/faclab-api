from sqlalchemy.orm import Session
from wireup import injectable

from src.shared.infra.repositories import SqlAlchemyRepository
from src.suppliers.app.repositories import (
    SupplierContactRepository,
    SupplierProductRepository,
    SupplierRepository,
)
from src.suppliers.domain.entities import Supplier, SupplierContact, SupplierProduct
from src.suppliers.domain.exceptions import (
    SupplierProductAlreadyExistsError,
    SupplierTaxIdAlreadyExistsError,
)
from src.suppliers.infra.mappers import (
    SupplierContactMapper,
    SupplierMapper,
    SupplierProductMapper,
)
from src.suppliers.infra.models import (
    SupplierContactModel,
    SupplierModel,
    SupplierProductModel,
)


@injectable(lifetime="scoped", as_type=SupplierRepository)
class SqlAlchemySupplierRepository(SqlAlchemyRepository[Supplier], SupplierRepository):
    __model__ = SupplierModel
    __unique_errors__ = {
        "suppliers_tax_id_key": SupplierTaxIdAlreadyExistsError,
    }

    def __init__(self, session: Session, mapper: SupplierMapper):
        super().__init__(session, mapper)


@injectable(lifetime="scoped", as_type=SupplierContactRepository)
class SqlAlchemySupplierContactRepository(
    SqlAlchemyRepository[SupplierContact], SupplierContactRepository
):
    __model__ = SupplierContactModel

    def __init__(self, session: Session, mapper: SupplierContactMapper):
        super().__init__(session, mapper)


@injectable(lifetime="scoped", as_type=SupplierProductRepository)
class SqlAlchemySupplierProductRepository(
    SqlAlchemyRepository[SupplierProduct], SupplierProductRepository
):
    __model__ = SupplierProductModel
    __unique_errors__ = {
        "supplier_products_supplier_id_product_id_key": SupplierProductAlreadyExistsError,
    }

    def __init__(self, session: Session, mapper: SupplierProductMapper):
        super().__init__(session, mapper)
