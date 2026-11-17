from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session
from wireup import injectable

from src.catalog.product.infra.models import ProductPresentationModel
from src.public_api.app.listing import Page, PageRequest, columns_of, ordering, paginate
from src.sales.domain.entities import SaleItem
from src.sales.infra.models import PaymentModel, SaleItemModel, SaleModel
from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.exceptions import NotFoundError
from src.shared.domain.tax import TaxCode
from src.shared.infra.tenant import tenant_criteria

SORT_FIELDS = {
    "id": SaleModel.id,
    "saleDate": SaleModel.sale_date,
    "createdAt": SaleModel.created_at,
    "updatedAt": SaleModel.updated_at,
}


@dataclass
class ListApiSalesQuery(Query):
    page: PageRequest = field(default_factory=PageRequest)
    # The client's branches; None, every one
    allowed_branch_ids: frozenset[int] | None = None
    branch_id: int | None = None
    status: str | None = None
    invoice_status: str | None = None
    channel: str | None = None
    external_reference: str | None = None
    # By the moment it was sold (confirmed)
    sold_from: datetime | None = None
    sold_to: datetime | None = None


@injectable(lifetime="scoped")
class ListApiSalesQueryHandler(QueryHandler[ListApiSalesQuery, Page]):
    """The sales of the client's branches, of every channel, with their items,
    payments and invoice status. Drafts are the POS's work in progress: never
    listed."""

    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: ListApiSalesQuery) -> Page:
        statement = select(SaleModel).where(
            *tenant_criteria(SaleModel), SaleModel.status != "DRAFT"
        )
        if query.allowed_branch_ids is not None:
            statement = statement.where(
                SaleModel.branch_id.in_(query.allowed_branch_ids)
            )
        filters = {
            SaleModel.branch_id: query.branch_id,
            SaleModel.status: query.status,
            SaleModel.invoice_status: query.invoice_status,
            SaleModel.channel: query.channel,
            SaleModel.external_reference: query.external_reference,
        }
        for column, value in filters.items():
            if value is not None:
                statement = statement.where(column == value)
        if query.sold_from is not None:
            statement = statement.where(SaleModel.sale_date >= query.sold_from)
        if query.sold_to is not None:
            statement = statement.where(SaleModel.sale_date < query.sold_to)
        if query.page.updated_since is not None:
            statement = statement.where(
                SaleModel.updated_at >= query.page.updated_since
            )
        page = paginate(
            self.session,
            statement,
            ordering(query.page, SORT_FIELDS, SaleModel.id),
            query.page,
        )
        return Page(
            items=sale_views(self.session, page.items),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )


@dataclass
class GetApiSaleQuery(Query):
    sale_id: int
    allowed_branch_ids: frozenset[int] | None = None


@injectable(lifetime="scoped")
class GetApiSaleQueryHandler(QueryHandler[GetApiSaleQuery, dict]):
    """A sale of the client's branches (another branch's, or a draft, looks
    missing)"""

    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: GetApiSaleQuery) -> dict:
        statement = select(SaleModel).where(
            *tenant_criteria(SaleModel),
            SaleModel.id == query.sale_id,
            SaleModel.status != "DRAFT",
        )
        if query.allowed_branch_ids is not None:
            statement = statement.where(
                SaleModel.branch_id.in_(query.allowed_branch_ids)
            )
        model = self.session.scalar(statement)
        if model is None:
            raise NotFoundError(f"Sale with id {query.sale_id} not found")
        [view] = sale_views(self.session, [model])
        return view


def sale_views(session: Session, sales: list[SaleModel]) -> list[dict]:
    """The sales with their items (and the name of their presentation) and
    their payments, read in two queries"""
    ids = [sale.id for sale in sales]
    items: dict[int, list[dict]] = {}
    payments: dict[int, list[dict]] = {}
    if ids:
        rows = session.execute(
            select(SaleItemModel, ProductPresentationModel.name)
            .outerjoin(
                ProductPresentationModel,
                ProductPresentationModel.id == SaleItemModel.presentation_id,
            )
            .where(
                *tenant_criteria(SaleItemModel),
                SaleItemModel.sale_id.in_(ids),
            )
            .order_by(SaleItemModel.id)
        )
        for item, presentation_name in rows:
            items.setdefault(item.sale_id, []).append(
                _item_view(item, presentation_name)
            )
        for payment in session.scalars(
            select(PaymentModel)
            .where(*tenant_criteria(PaymentModel), PaymentModel.sale_id.in_(ids))
            .order_by(PaymentModel.id)
        ):
            payments.setdefault(payment.sale_id, []).append(columns_of(payment))
    return [
        {
            **columns_of(sale),
            "items": items.get(sale.id, []),
            "payments": payments.get(sale.id, []),
        }
        for sale in sales
    ]


def _item_view(item: SaleItemModel, presentation_name: str | None) -> dict:
    line = SaleItem(
        sale_id=item.sale_id,
        product_id=item.product_id,
        quantity=item.quantity,
        unit_price=item.unit_price,
        discount=item.discount,
        tax_code=TaxCode(item.tax_code),
        tax_amount=item.tax_amount,
        unit_factor=item.unit_factor,
    )
    return {
        **columns_of(item),
        "presentation_name": presentation_name,
        "subtotal": line.subtotal,
    }
