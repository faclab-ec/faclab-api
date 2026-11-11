"""The PDF of a quote: what it shows and that reportlab draws it (S5.4)"""

import re
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

from src.customers.domain.entities import Customer
from src.quotes.app.document import QuoteDocuments, tax_label
from src.quotes.infra.pdf import ReportLabQuoteRenderer, quantity
from src.shared.domain.tax import TaxCode
from tests.conftest import TEST_TENANT_ID
from tests.unit.quotes.fakes import (
    NEXT_WEEK,
    TODAY,
    InMemoryQuoteItems,
    catalog,
    draft,
    line,
)


def _documents(items, customer=None, renderer=None):
    tenants = Mock()
    tenants.get.return_value = SimpleNamespace(
        id=TEST_TENANT_ID,
        ruc="1790012345001",
        legal_name="Ferretería El Clavo S.A.",
        trade_name="El Clavo",
    )
    branches = Mock()
    branches.get_by_id.return_value = SimpleNamespace(
        name="Matriz", establishment_code="001", address="Av. Loja 1-23"
    )
    customers = Mock()
    customers.get_by_id.return_value = customer
    products, presentations = catalog()
    return QuoteDocuments(
        tenants,
        branches,
        customers,
        products,
        presentations,
        InMemoryQuoteItems(*items),
        renderer or ReportLabQuoteRenderer(),
    )


def _quote_with_lines():
    items = [
        line(id=1, quantity=Decimal(3), discount=Decimal(10)),
        line(
            id=2,
            product_id=200,
            presentation_id=21,
            quantity=Decimal("1.5"),
            unit_price=Decimal("4.50"),
            tax_code=TaxCode.VAT_0,
        ),
    ]
    quote = draft(notes="Entrega en obra")
    quote.recalculate_totals(items)
    return quote, items


def test_the_document_names_its_issuer_customer_lines_and_taxes(in_tenant):
    quote, items = _quote_with_lines()
    customer = Customer(
        id=5, name="Ana Pérez", tax_id="0102030405", email="ana@example.com"
    )

    document = _documents(items, customer).document(quote)

    assert (document.issuer_ruc, document.sender_name) == ("1790012345001", "El Clavo")
    assert (document.branch_name, document.establishment_code) == ("Matriz", "001")
    assert (document.customer_name, document.customer_email) == (
        "Ana Pérez",
        "ana@example.com",
    )
    assert [(row.code, row.description) for row in document.lines] == [
        ("FERR-003", "Cemento"),
        ("FERR-010", "Tornillo 1/2 (Caja x100)"),
    ]
    # 3 × 9.50 − 10% = 25.65 at 15%; 1.5 × 4.50 = 6.75 at 0%
    assert [(t.label, t.base, t.tax) for t in document.taxes] == [
        ("IVA 15%", Decimal("25.65"), Decimal("3.85")),
        ("IVA 0%", Decimal("6.75"), Decimal("0.00")),
    ]
    assert document.total == document.subtotal + document.tax == Decimal("36.25")
    assert document.filename == "cotizacion-COT-001-000001.pdf"
    assert (document.issue_date, document.valid_until) == (TODAY, NEXT_WEEK)


def test_a_quote_to_the_final_consumer_has_no_customer(in_tenant):
    quote, items = _quote_with_lines()

    document = _documents(items).document(draft(customer_id=None))

    assert document.customer_name is None


def test_reportlab_draws_a_pdf(in_tenant):
    quote, items = _quote_with_lines()

    _, pdf = _documents(items).pdf(quote)

    assert pdf.startswith(b"%PDF-")
    assert pdf.rstrip().endswith(b"%%EOF")


def test_a_long_quote_takes_several_pages(in_tenant):
    items = [line(id=i, quantity=Decimal(i)) for i in range(1, 121)]
    quote = draft(notes="Línea 1\nLínea 2 <con> & símbolos")
    quote.recalculate_totals(items)

    _, pdf = _documents(items).pdf(quote)

    [pages] = re.findall(rb"/Count (\d+)", pdf)
    assert int(pages) > 1


def test_labels_and_quantities_read_well():
    assert tax_label(TaxCode.VAT_15) == "IVA 15%"
    assert tax_label(TaxCode.VAT_0) == "IVA 0%"
    assert tax_label(TaxCode.EXEMPT) == "Exento de IVA"
    assert tax_label(TaxCode.NOT_TAXED) == "No objeto de IVA"
    assert quantity(Decimal("2.500000")) == "2.5"
    assert quantity(Decimal("100.000000")) == "100"
