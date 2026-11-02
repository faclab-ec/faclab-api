from collections.abc import Iterable
from datetime import datetime

from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session
from wireup import injectable

from src.invoicing.app.repositories import (
    CreditNoteRepository,
    InvoiceDiscrepancyRepository,
)
from src.invoicing.domain.entities import (
    CreditNote,
    DiscrepancyKind,
    DiscrepancyStatus,
    InvoiceDiscrepancy,
)
from src.invoicing.infra.mappers import CreditNoteMapper, InvoiceDiscrepancyMapper
from src.invoicing.infra.models import CreditNoteModel, InvoiceDiscrepancyModel
from src.shared.domain.tenant import require_tenant
from src.shared.infra.repositories import SqlAlchemyRepository


@injectable(lifetime="scoped", as_type=InvoiceDiscrepancyRepository)
class SqlAlchemyInvoiceDiscrepancyRepository(
    SqlAlchemyRepository[InvoiceDiscrepancy], InvoiceDiscrepancyRepository
):
    __model__ = InvoiceDiscrepancyModel

    # The partial unique index uq_invoice_discrepancies_tenant_sale_kind_unresolved
    _KEY = ("tenant_id", "sale_id", "kind")

    def __init__(self, session: Session, mapper: InvoiceDiscrepancyMapper):
        super().__init__(session, mapper)

    def open(
        self, sale_id: int, kind: DiscrepancyKind, invoice_id: str | None = None
    ) -> bool:
        """A Core statement, so the tenant is set here (`assign_tenant` doesn't
        see it); a conflict with an unresolved one inserts nothing"""
        values = {
            "tenant_id": require_tenant("opening an invoice discrepancy").tenant_id,
            "sale_id": sale_id,
            "kind": kind.value,
            "status": DiscrepancyStatus.OPEN.value,
            "invoice_id": invoice_id,
            "detected_at": datetime.now(),
        }
        unresolved = InvoiceDiscrepancyModel.status != DiscrepancyStatus.RESOLVED.value
        if self.session.get_bind().dialect.name == "postgresql":
            statement = (
                postgresql.insert(InvoiceDiscrepancyModel)
                .values(**values)
                .on_conflict_do_nothing(
                    index_elements=self._KEY, index_where=unresolved
                )
            )
        else:
            statement = (
                sqlite.insert(InvoiceDiscrepancyModel)
                .values(**values)
                .on_conflict_do_nothing(
                    index_elements=self._KEY, index_where=unresolved
                )
            )
        returning = statement.returning(InvoiceDiscrepancyModel.id)
        return self.session.execute(returning).scalar_one_or_none() is not None

    def unresolved(
        self, kind: DiscrepancyKind, sale_id: int | None = None
    ) -> list[InvoiceDiscrepancy]:
        criteria = [
            InvoiceDiscrepancyModel.kind == kind.value,
            InvoiceDiscrepancyModel.status != DiscrepancyStatus.RESOLVED.value,
        ]
        if sale_id is not None:
            criteria.append(InvoiceDiscrepancyModel.sale_id == sale_id)
        return self.filter(criteria=criteria, order_by="id")


@injectable(lifetime="scoped", as_type=CreditNoteRepository)
class SqlAlchemyCreditNoteRepository(
    SqlAlchemyRepository[CreditNote], CreditNoteRepository
):
    __model__ = CreditNoteModel

    def __init__(self, session: Session, mapper: CreditNoteMapper):
        super().__init__(session, mapper)

    def of_refunds(self, refund_ids: Iterable[int]) -> list[CreditNote]:
        ids = list(refund_ids)
        if not ids:
            return []
        return self.filter(criteria=[CreditNoteModel.refund_id.in_(ids)])

    def of_cancelled_sale(self, sale_id: int) -> CreditNote | None:
        notes = self.filter(
            criteria=[
                CreditNoteModel.sale_id == sale_id,
                CreditNoteModel.refund_id.is_(None),
            ]
        )
        return notes[0] if notes else None
