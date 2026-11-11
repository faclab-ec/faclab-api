"""El PDF de una cotización con reportlab (S5.4): A4, la empresa y la sucursal,
el cliente, la tabla de ítems, los totales por tarifa de IVA y las notas.

reportlab (BSD) es Python puro desde la 4.0: no necesita bibliotecas del sistema
en la imagen. Usa las fuentes estándar del PDF (Helvetica), que cubren el
español."""

from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Flowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from wireup import injectable

from src.quotes.app.document import QuoteDocument, QuotePdfRenderer

_FOOTER = (
    "Documento sin valor tributario. Los precios rigen hasta la fecha de validez; "
    "la cotización no reserva mercadería."
)
_GRID = colors.HexColor("#d1d5db")
_HEADER = colors.HexColor("#f3f4f6")


def money(value: Decimal) -> str:
    return f"${value:,.2f}"


def quantity(value: Decimal) -> str:
    """Sin ceros de sobra: 2, 2.5, 0.125"""
    return f"{value.normalize():f}"


def percentage(value: Decimal) -> str:
    return f"{value.normalize():f}%" if value else ""


@injectable(lifetime="singleton", as_type=QuotePdfRenderer)
class ReportLabQuoteRenderer(QuotePdfRenderer):
    def __init__(self):
        styles = getSampleStyleSheet()
        self.normal = ParagraphStyle(
            "QuoteNormal", parent=styles["Normal"], fontSize=9, leading=12
        )
        self.small = ParagraphStyle(
            "QuoteSmall", parent=self.normal, fontSize=8, leading=10
        )
        self.title = ParagraphStyle(
            "QuoteTitle", parent=styles["Title"], fontSize=15, alignment=TA_RIGHT
        )
        self.issuer = ParagraphStyle(
            "QuoteIssuer", parent=styles["Heading2"], fontSize=13, spaceAfter=2
        )
        self.right = ParagraphStyle(
            "QuoteRight", parent=self.normal, alignment=TA_RIGHT
        )

    def render(self, document: QuoteDocument) -> bytes:
        buffer = BytesIO()
        pdf = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=15 * mm,
            rightMargin=15 * mm,
            topMargin=15 * mm,
            bottomMargin=18 * mm,
            title=f"Cotización {document.number}",
            author=document.sender_name,
        )
        story: list[Flowable] = [
            self._heading(document),
            Spacer(1, 5 * mm),
            self._customer(document),
            Spacer(1, 5 * mm),
            self._items(document),
            Spacer(1, 3 * mm),
            self._totals(document),
        ]
        if document.notes:
            story += [
                Spacer(1, 5 * mm),
                Paragraph("<b>Notas</b>", self.normal),
                Paragraph(_text(document.notes), self.normal),
            ]
        pdf.build(story, onFirstPage=self._footer, onLaterPages=self._footer)
        return buffer.getvalue()

    def _heading(self, document: QuoteDocument) -> Table:
        issuer = [Paragraph(_text(document.sender_name), self.issuer)]
        if document.issuer_trade_name:
            issuer.append(Paragraph(_text(document.issuer_name), self.normal))
        issuer.append(Paragraph(f"RUC {_text(document.issuer_ruc)}", self.normal))
        branch = f"{document.branch_name} ({document.establishment_code})"
        issuer.append(Paragraph(_text(branch), self.normal))
        if document.branch_address:
            issuer.append(Paragraph(_text(document.branch_address), self.normal))
        number = [
            Paragraph("COTIZACIÓN", self.title),
            Paragraph(f"<b>{_text(document.number)}</b>", self.right),
            Paragraph(f"Emitida: {document.issue_date:%d/%m/%Y}", self.right),
            Paragraph(
                f"<b>Válida hasta: {document.valid_until:%d/%m/%Y}</b>", self.right
            ),
        ]
        table = Table([[issuer, number]], colWidths=["60%", "40%"])
        table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        return table

    def _customer(self, document: QuoteDocument) -> Table:
        if document.customer_name is None:
            name, tax_id = "Consumidor final", ""
        else:
            name = document.customer_name
            tax_id = f"<b>RUC/Cédula:</b> {_text(document.customer_tax_id or '')}"
        rows = [
            [
                Paragraph(f"<b>Cliente:</b> {_text(name)}", self.normal),
                Paragraph(tax_id, self.normal),
            ]
        ]
        contact = [
            value
            for value in (
                document.customer_address,
                document.customer_phone,
                document.customer_email,
            )
            if value
        ]
        style = [
            ("BOX", (0, 0), (-1, -1), 0.5, _GRID),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
        if contact:
            rows.append([Paragraph(_text(" · ".join(contact)), self.normal), ""])
            style.append(("SPAN", (0, 1), (-1, 1)))
        table = Table(rows, colWidths=["65%", "35%"])
        table.setStyle(TableStyle(style))
        return table

    def _items(self, document: QuoteDocument) -> Table:
        header = ["Código", "Descripción", "Cant.", "P. unitario", "Desc.", "Subtotal"]
        rows: list[list] = [header]
        for line in document.lines:
            rows.append(
                [
                    Paragraph(_text(line.code), self.small),
                    Paragraph(_text(line.description), self.small),
                    quantity(line.quantity),
                    money(line.unit_price),
                    percentage(line.discount),
                    money(line.subtotal),
                ]
            )
        table = Table(
            rows,
            colWidths=[25 * mm, 72 * mm, 18 * mm, 24 * mm, 15 * mm, 26 * mm],
            repeatRows=1,
        )
        table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("BACKGROUND", (0, 0), (-1, 0), _HEADER),
                    ("GRID", (0, 0), (-1, -1), 0.5, _GRID),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
                ]
            )
        )
        return table

    def _totals(self, document: QuoteDocument) -> Table:
        rows = [[f"Subtotal {tax.label}", money(tax.base)] for tax in document.taxes]
        rows.append(["Subtotal", money(document.subtotal)])
        rows.append(["IVA", money(document.tax)])
        rows.append(["TOTAL", money(document.total)])
        table = Table(rows, colWidths=[45 * mm, 26 * mm], hAlign="RIGHT")
        table.setStyle(
            TableStyle(
                [
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                    ("LINEABOVE", (0, -1), (-1, -1), 0.75, colors.black),
                ]
            )
        )
        return table

    def _footer(self, canvas, pdf) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#6b7280"))
        canvas.drawString(pdf.leftMargin, 10 * mm, _FOOTER)
        canvas.drawRightString(
            A4[0] - pdf.rightMargin, 10 * mm, f"Página {canvas.getPageNumber()}"
        )
        canvas.restoreState()


def _text(value: str) -> str:
    """Texto libre dentro de un Paragraph, que interpreta etiquetas"""
    return escape(value).replace("\n", "<br/>")
