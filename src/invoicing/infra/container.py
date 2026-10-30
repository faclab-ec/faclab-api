from src.invoicing.app.commands.discrepancies import (
    OpenInvoiceDiscrepancyCommandHandler,
    ReconcileInvoicesCommandHandler,
    ResolveInvoiceDiscrepancyCommandHandler,
    ReviewInvoiceDiscrepancyCommandHandler,
)
from src.invoicing.app.queries.discrepancies import ListInvoiceDiscrepanciesQueryHandler
from src.invoicing.infra.mappers import InvoiceDiscrepancyMapper
from src.invoicing.infra.repositories import SqlAlchemyInvoiceDiscrepancyRepository

INJECTABLES = [
    InvoiceDiscrepancyMapper,
    SqlAlchemyInvoiceDiscrepancyRepository,
    ReconcileInvoicesCommandHandler,
    OpenInvoiceDiscrepancyCommandHandler,
    ResolveInvoiceDiscrepancyCommandHandler,
    ReviewInvoiceDiscrepancyCommandHandler,
    ListInvoiceDiscrepanciesQueryHandler,
]
