from src.receivables.app.commands.payments import RecordCustomerPaymentCommandHandler
from src.receivables.app.credit import CustomerCredit
from src.receivables.app.queries.receivables import (
    GetCustomerAccountQueryHandler,
    GetCustomerPaymentQueryHandler,
    GetCustomerPaymentsQueryHandler,
    GetCustomerStatementQueryHandler,
    GetReceivableQueryHandler,
    GetReceivablesAgingQueryHandler,
    GetReceivablesQueryHandler,
)
from src.receivables.infra.mappers import (
    CustomerPaymentMapper,
    ReceivableApplicationMapper,
    ReceivableMapper,
)
from src.receivables.infra.repositories import (
    SqlAlchemyCustomerPaymentRepository,
    SqlAlchemyReceivableApplicationRepository,
    SqlAlchemyReceivableRepository,
)

INJECTABLES = [
    ReceivableMapper,
    ReceivableApplicationMapper,
    CustomerPaymentMapper,
    SqlAlchemyReceivableRepository,
    SqlAlchemyReceivableApplicationRepository,
    SqlAlchemyCustomerPaymentRepository,
    CustomerCredit,
    RecordCustomerPaymentCommandHandler,
    GetReceivablesQueryHandler,
    GetReceivableQueryHandler,
    GetReceivablesAgingQueryHandler,
    GetCustomerAccountQueryHandler,
    GetCustomerStatementQueryHandler,
    GetCustomerPaymentsQueryHandler,
    GetCustomerPaymentQueryHandler,
]
