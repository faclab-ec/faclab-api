"""El PDF de una cotización (S5.4): lo que muestra, armado aquí, y un puerto que
lo dibuja (`ReportLabQuoteRenderer` en infra)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from wireup import injectable

from src.catalog.product.app.repositories import (
    ProductPresentationRepository,
    ProductRepository,
)
from src.catalog.product.domain.entities import line_name
from src.customers.app.repositories import CustomerRepository
from src.organization.app.repositories import BranchRepository
from src.quotes.app.repositories import QuoteItemRepository
from src.quotes.domain.entities import Quote, QuoteItem
from src.shared.domain.tax import TaxCode
from src.shared.domain.tenant import require_tenant
from src.tenancy.app.repositories import TenantRepository

_TAX_LABELS = {
    TaxCode.EXEMPT: "Exento de IVA",
    TaxCode.NOT_TAXED: "No objeto de IVA",
    TaxCode.VAT_8_TOURISM: "IVA 8% (turismo)",
}


def tax_label(code: TaxCode) -> str:
    return _TAX_LABELS.get(code) or f"IVA {code.rate.normalize():f}%"


@dataclass(frozen=True)
class QuoteDocumentLine:
    code: str
    description: str
    quantity: Decimal
    unit_price: Decimal
    discount: Decimal
    subtotal: Decimal


@dataclass(frozen=True)
class QuoteTaxLine:
    """La base y el IVA de una tarifa"""

    label: str
    base: Decimal
    tax: Decimal


@dataclass(frozen=True)
class QuoteDocument:
    number: str
    issue_date: date
    valid_until: date
    issuer_name: str
    issuer_ruc: str
    branch_name: str
    establishment_code: str
    lines: tuple[QuoteDocumentLine, ...]
    taxes: tuple[QuoteTaxLine, ...]
    subtotal: Decimal
    tax: Decimal
    total: Decimal
    issuer_trade_name: str | None = None
    branch_address: str | None = None
    # None: final consumer
    customer_name: str | None = None
    customer_tax_id: str | None = None
    customer_address: str | None = None
    customer_email: str | None = None
    customer_phone: str | None = None
    notes: str | None = None
    created_by: str | None = None

    @property
    def sender_name(self) -> str:
        """El nombre con que la empresa firma: el comercial o la razón social"""
        return self.issuer_trade_name or self.issuer_name

    @property
    def filename(self) -> str:
        return f"cotizacion-{self.number}.pdf"


class QuotePdfRenderer(ABC):
    @abstractmethod
    def render(self, document: QuoteDocument) -> bytes:
        """El PDF del documento"""


@injectable(lifetime="scoped")
class QuoteDocuments:
    def __init__(
        self,
        tenants: TenantRepository,
        branches: BranchRepository,
        customers: CustomerRepository,
        products: ProductRepository,
        presentations: ProductPresentationRepository,
        items: QuoteItemRepository,
        renderer: QuotePdfRenderer,
    ):
        self.tenants = tenants
        self.branches = branches
        self.customers = customers
        self.products = products
        self.presentations = presentations
        self.items = items
        self.renderer = renderer

    def pdf(self, quote: Quote) -> tuple[QuoteDocument, bytes]:
        document = self.document(quote)
        return document, self.renderer.render(document)

    def document(
        self, quote: Quote, items: list[QuoteItem] | None = None
    ) -> QuoteDocument:
        if items is None:
            items = self.items.for_quote(quote.require_id())
        tenant = self.tenants.get(require_tenant("printing a quote").tenant_id)
        branch = self.branches.get_by_id(quote.branch_id)
        customer = (
            self.customers.get_by_id(quote.customer_id) if quote.customer_id else None
        )
        products = {
            p.require_id(): p
            for p in self.products.get_by_ids(i.product_id for i in items)
        }
        presentations = {
            p.require_id(): p
            for p in self.presentations.get_by_ids(
                i.presentation_id for i in items if i.presentation_id is not None
            )
        }
        lines = []
        for item in items:
            product = products.get(item.product_id)
            lines.append(
                QuoteDocumentLine(
                    code=product.sku if product else str(item.product_id),
                    description=line_name(
                        product, presentations.get(item.presentation_id or 0)
                    )
                    or "",
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    discount=item.discount,
                    subtotal=item.subtotal,
                )
            )
        taxes = tuple(
            QuoteTaxLine(tax_label(code), base, tax)
            for code, (base, tax) in sorted(
                Quote.tax_breakdown(items).items(),
                key=lambda entry: entry[0].rate,
                reverse=True,
            )
        )
        return QuoteDocument(
            number=quote.number or "",
            issue_date=quote.issue_date,
            valid_until=quote.valid_until,
            issuer_name=tenant.legal_name if tenant else "",
            issuer_trade_name=tenant.trade_name if tenant else None,
            issuer_ruc=tenant.ruc if tenant else "",
            branch_name=branch.name if branch else "",
            establishment_code=branch.establishment_code if branch else "",
            branch_address=branch.address if branch else None,
            customer_name=customer.name if customer else None,
            customer_tax_id=customer.tax_id if customer else None,
            customer_address=customer.address if customer else None,
            customer_email=customer.email if customer else None,
            customer_phone=customer.phone if customer else None,
            lines=tuple(lines),
            taxes=taxes,
            subtotal=quote.subtotal,
            tax=quote.tax,
            total=quote.total,
            notes=quote.notes,
            created_by=quote.created_by,
        )
