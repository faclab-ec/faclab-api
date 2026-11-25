"""The electronic documents the SRI authorized, counted per month (S8.4).

faclab-invoicing only issues what the core asks for, so every authorized
document comes back to the core: an invoice as `SaleInvoiced`, a credit note
as `CreditNoteAuthorized`. Both are published once per document (their
commands are idempotent by state), in the transaction that applies the result.
The monthly limit is soft: nothing stops the invoicing of what was sold.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

import structlog
from wireup import injectable

from src.shared.app.commands import Command, CommandHandler
from src.subscriptions.app.plans import TenantPlan
from src.subscriptions.app.repositories import DocumentUsageRepository
from src.subscriptions.domain.entities import period_of

logger = structlog.get_logger(__name__)


class DocumentKind(StrEnum):
    INVOICE = "invoice"
    CREDIT_NOTE = "credit_note"


@dataclass
class CountDocumentCommand(Command):
    kind: DocumentKind
    # When the core learned it was authorized: the month it counts in
    occurred_at: datetime


@injectable(lifetime="scoped")
class CountDocumentCommandHandler(CommandHandler[CountDocumentCommand, dict]):
    def __init__(self, usage: DocumentUsageRepository, plan: TenantPlan):
        self.usage = usage
        self.plan = plan

    def _handle(self, command: CountDocumentCommand) -> dict:
        is_invoice = command.kind is DocumentKind.INVOICE
        month = self.usage.count(
            period_of(command.occurred_at),
            invoices=1 if is_invoice else 0,
            credit_notes=0 if is_invoice else 1,
        )
        _, plan = self.plan.current()
        limit = plan.max_monthly_documents if plan is not None else None
        # Once, when this document is the first beyond the plan
        if limit is not None and month.total == limit + 1:
            logger.warning(
                "plan_documents_limit_exceeded",
                period=month.period.isoformat(),
                limit=limit,
                plan=plan.code if plan is not None else None,
            )
        return {
            "period": month.period,
            "invoices": month.invoices,
            "credit_notes": month.credit_notes,
        }
