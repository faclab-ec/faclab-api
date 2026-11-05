from src.invoicing.app.commands.credit_notes import (
    ApplyCreditNoteResultCommandHandler,
    RequestCancelledSaleCreditNoteCommandHandler,
    RequestCreditNoteAgainCommandHandler,
    RequestRefundCreditNotesCommandHandler,
)
from src.invoicing.app.commands.discrepancies import (
    OpenInvoiceDiscrepancyCommandHandler,
    ReconcileInvoicesCommandHandler,
    ResolveInvoiceDiscrepancyCommandHandler,
    ReviewInvoiceDiscrepancyCommandHandler,
)
from src.invoicing.app.queries.discrepancies import ListInvoiceDiscrepanciesQueryHandler
from src.invoicing.infra.mappers import CreditNoteMapper, InvoiceDiscrepancyMapper
from src.invoicing.infra.repositories import (
    SqlAlchemyCreditNoteRepository,
    SqlAlchemyInvoiceDiscrepancyRepository,
)

INJECTABLES = [
    InvoiceDiscrepancyMapper,
    SqlAlchemyInvoiceDiscrepancyRepository,
    ReconcileInvoicesCommandHandler,
    OpenInvoiceDiscrepancyCommandHandler,
    ResolveInvoiceDiscrepancyCommandHandler,
    ReviewInvoiceDiscrepancyCommandHandler,
    ListInvoiceDiscrepanciesQueryHandler,
    CreditNoteMapper,
    SqlAlchemyCreditNoteRepository,
    RequestRefundCreditNotesCommandHandler,
    RequestCancelledSaleCreditNoteCommandHandler,
    RequestCreditNoteAgainCommandHandler,
    ApplyCreditNoteResultCommandHandler,
]
