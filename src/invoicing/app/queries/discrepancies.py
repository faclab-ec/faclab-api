from dataclasses import dataclass

from sqlalchemy.orm import Session
from wireup import injectable

from src.invoicing.domain.entities import DiscrepancyStatus
from src.invoicing.infra.models import InvoiceDiscrepancyModel
from src.sales.infra.models import SaleModel
from src.shared.app.queries import Query, QueryHandler
from src.shared.infra.tenant import tenant_criteria


@dataclass
class ListInvoiceDiscrepanciesQuery(Query):
    status: str | None = DiscrepancyStatus.OPEN.value
    kind: str | None = None
    sale_id: int | None = None
    limit: int = 50
    offset: int = 0


@injectable(lifetime="scoped")
class ListInvoiceDiscrepanciesQueryHandler(
    QueryHandler[ListInvoiceDiscrepanciesQuery, dict]
):
    """Las discrepancias de la empresa, las más antiguas primero, con lo que la
    vista necesita de su venta para decidir qué hacer"""

    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: ListInvoiceDiscrepanciesQuery) -> dict:
        q = (
            self.session.query(InvoiceDiscrepancyModel, SaleModel)
            .join(SaleModel, SaleModel.id == InvoiceDiscrepancyModel.sale_id)
            .filter(*tenant_criteria(InvoiceDiscrepancyModel, SaleModel))
        )
        if query.status is not None:
            q = q.filter(InvoiceDiscrepancyModel.status == query.status)
        if query.kind is not None:
            q = q.filter(InvoiceDiscrepancyModel.kind == query.kind)
        if query.sale_id is not None:
            q = q.filter(InvoiceDiscrepancyModel.sale_id == query.sale_id)

        total = q.count()
        rows = (
            q.order_by(InvoiceDiscrepancyModel.id)
            .offset(query.offset)
            .limit(query.limit)
            .all()
        )
        return {
            "total": total,
            "limit": query.limit,
            "offset": query.offset,
            "items": [
                {
                    "id": discrepancy.id,
                    "kind": discrepancy.kind,
                    "status": discrepancy.status,
                    "sale_id": discrepancy.sale_id,
                    "invoice_id": discrepancy.invoice_id,
                    "detected_at": discrepancy.detected_at,
                    "resolved_at": discrepancy.resolved_at,
                    "reviewed_at": discrepancy.reviewed_at,
                    "reviewed_by_name": discrepancy.reviewed_by_name,
                    "review_note": discrepancy.review_note,
                    "sale": {
                        "id": sale.id,
                        "number": sale.number,
                        "status": sale.status,
                        "total": sale.total,
                        "branch_id": sale.branch_id,
                        "sale_date": sale.sale_date,
                        "invoice_status": sale.invoice_status,
                        "invoice_requested_at": sale.invoice_requested_at,
                    },
                }
                for discrepancy, sale in rows
            ],
        }
