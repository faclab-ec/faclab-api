from src.payables.app.accounts import SupplierAccounts
from src.payables.app.commands.payments import RecordSupplierPaymentCommandHandler
from src.payables.app.queries.payables import (
    GetPayableQueryHandler,
    GetPayablesQueryHandler,
    GetSupplierAccountQueryHandler,
    GetSupplierPaymentQueryHandler,
    GetSupplierPaymentsQueryHandler,
)
from src.payables.infra.mappers import (
    PayableApplicationMapper,
    PayableMapper,
    SupplierPaymentMapper,
)
from src.payables.infra.repositories import (
    SqlAlchemyPayableApplicationRepository,
    SqlAlchemyPayableRepository,
    SqlAlchemySupplierPaymentRepository,
)

INJECTABLES = [
    PayableMapper,
    PayableApplicationMapper,
    SupplierPaymentMapper,
    SqlAlchemyPayableRepository,
    SqlAlchemyPayableApplicationRepository,
    SqlAlchemySupplierPaymentRepository,
    SupplierAccounts,
    RecordSupplierPaymentCommandHandler,
    GetPayablesQueryHandler,
    GetPayableQueryHandler,
    GetSupplierAccountQueryHandler,
    GetSupplierPaymentsQueryHandler,
    GetSupplierPaymentQueryHandler,
]
