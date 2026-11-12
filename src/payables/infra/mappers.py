from wireup import injectable

from src.payables.domain.entities import Payable, PayableApplication, SupplierPayment
from src.payables.infra.models import (
    PayableApplicationModel,
    PayableModel,
    SupplierPaymentModel,
)
from src.shared.infra.mappers import Mapper


@injectable(lifetime="singleton")
class PayableMapper(Mapper[Payable, PayableModel]):
    __entity__ = Payable
    __exclude_fields__ = frozenset({"created_at", "updated_at"})


@injectable(lifetime="singleton")
class PayableApplicationMapper(Mapper[PayableApplication, PayableApplicationModel]):
    __entity__ = PayableApplication


@injectable(lifetime="singleton")
class SupplierPaymentMapper(Mapper[SupplierPayment, SupplierPaymentModel]):
    __entity__ = SupplierPayment
    __exclude_fields__ = frozenset({"created_at"})
