from wireup import injectable

from src.receivables.domain.entities import (
    CustomerPayment,
    Receivable,
    ReceivableApplication,
)
from src.receivables.infra.models import (
    CustomerPaymentModel,
    ReceivableApplicationModel,
    ReceivableModel,
)
from src.shared.infra.mappers import Mapper


@injectable(lifetime="singleton")
class ReceivableMapper(Mapper[Receivable, ReceivableModel]):
    __entity__ = Receivable
    __exclude_fields__ = frozenset({"created_at", "updated_at"})


@injectable(lifetime="singleton")
class ReceivableApplicationMapper(
    Mapper[ReceivableApplication, ReceivableApplicationModel]
):
    __entity__ = ReceivableApplication


@injectable(lifetime="singleton")
class CustomerPaymentMapper(Mapper[CustomerPayment, CustomerPaymentModel]):
    __entity__ = CustomerPayment
    __exclude_fields__ = frozenset({"created_at"})
