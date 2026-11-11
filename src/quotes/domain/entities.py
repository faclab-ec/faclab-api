"""Cotizaciones (S5.4): la proforma que una ferretería entrega para una obra.

Se numera por sucursal al crearla (`COT-001-000012`, ADR-0012), con el cliente
(o consumidor final), sus ítems a los precios de sus listas (S5.3) y la fecha
hasta la que rige. No reserva stock: la venta lo descuenta al cobrarse.

Estados:

- DRAFT: se edita (cabecera e ítems) y se puede borrar.
- SENT: entregada al cliente, a mano o por correo.
- ACCEPTED: el cliente la aceptó.
- EXPIRED: pasó su fecha sin convertirse (la tarea del worker la marca; antes,
  `is_expired` ya la trata como vencida). Se renueva con una fecha nueva: vuelve
  a DRAFT con los precios de ese día.
- CONVERTED: se cobró en el POS como una venta con sus mismos ítems.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from src.quotes.domain.exceptions import (
    InvalidQuoteStatusError,
    QuoteAlreadyConvertedError,
    QuoteExpiredError,
    QuoteWithoutItemsError,
)
from src.sales.domain.services import tax_breakdown
from src.shared.domain.entities import Entity
from src.shared.domain.exceptions import InvalidValueError
from src.shared.domain.money import round_money
from src.shared.domain.tax import TaxCode


class QuoteStatus(StrEnum):
    """Estado de una cotización"""

    DRAFT = "DRAFT"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    EXPIRED = "EXPIRED"
    CONVERTED = "CONVERTED"


# The ones that still can be sent, accepted or converted while in force
OPEN_QUOTE_STATUSES = (QuoteStatus.DRAFT, QuoteStatus.SENT, QuoteStatus.ACCEPTED)


@dataclass
class QuoteItem(Entity):
    """Una línea de la cotización, en una presentación del producto (S5.2), con
    el precio de su lista. Calcula como una línea de venta (`SaleItem`), así el
    total cotizado es el que cobra la venta."""

    quote_id: int
    product_id: int
    quantity: Decimal
    unit_price: Decimal
    discount: Decimal = Decimal("0")
    tax_code: TaxCode = TaxCode.VAT_15
    tax_amount: Decimal = Decimal("0")
    id: int | None = None
    presentation_id: int | None = None
    unit_factor: Decimal = Decimal(1)

    @property
    def base_quantity(self) -> Decimal:
        return self.quantity * self.unit_factor

    @property
    def subtotal(self) -> Decimal:
        base = self.unit_price * self.quantity
        return base - base * (self.discount / Decimal("100"))

    def recalculate_tax(self) -> None:
        self.tax_amount = self.subtotal * self.tax_code.rate / Decimal("100")


@dataclass
class Quote(Entity):
    branch_id: int
    valid_until: date
    number: str | None = None
    # None: final consumer
    customer_id: int | None = None
    status: QuoteStatus = QuoteStatus.DRAFT
    issue_date: date = field(default_factory=date.today)
    subtotal: Decimal = Decimal("0")
    tax: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    notes: str | None = None
    created_by: str | None = None
    sent_at: datetime | None = None
    accepted_at: datetime | None = None
    converted_at: datetime | None = None
    id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def draft(
        cls,
        *,
        branch_id: int,
        valid_until: date,
        today: date,
        customer_id: int | None = None,
        notes: str | None = None,
        created_by: str | None = None,
    ) -> "Quote":
        """Una cotización nueva, emitida hoy; el número se le da después de
        validarla, para no gastar uno en una fecha inválida"""
        quote = cls(
            branch_id=branch_id,
            valid_until=valid_until,
            issue_date=today,
            customer_id=customer_id,
            notes=notes,
            created_by=created_by,
        )
        quote._ensure_validity(valid_until, today)
        return quote

    def ensure_draft(self, operation: str) -> None:
        if self.status != QuoteStatus.DRAFT:
            raise InvalidQuoteStatusError(self.status, operation)

    def is_expired(self, today: date) -> bool:
        """Vencida: marcada por la tarea o abierta con su fecha ya pasada"""
        if self.status == QuoteStatus.EXPIRED:
            return True
        return self.status in OPEN_QUOTE_STATUSES and self.valid_until < today

    def change(
        self,
        *,
        customer_id: int | None,
        valid_until: date,
        notes: str | None,
        today: date,
    ) -> None:
        """Reemplaza los datos de un borrador"""
        self.ensure_draft("update")
        self._ensure_validity(valid_until, today)
        self.customer_id = customer_id
        self.valid_until = valid_until
        self.notes = notes

    def send(self, item_count: int, today: date) -> None:
        """Entregada al cliente (impresa o a mano)"""
        self.ensure_draft("send")
        self._ensure_usable(item_count, today)
        self.status = QuoteStatus.SENT
        self.sent_at = datetime.now()

    def mark_emailed(self, item_count: int, today: date) -> None:
        """Enviada por correo: un borrador pasa a SENT; una enviada o aceptada
        se puede reenviar"""
        if self.status not in OPEN_QUOTE_STATUSES:
            raise InvalidQuoteStatusError(self.status, "email")
        self._ensure_usable(item_count, today)
        if self.status == QuoteStatus.DRAFT:
            self.status = QuoteStatus.SENT
        self.sent_at = datetime.now()

    def accept(self, item_count: int, today: date) -> None:
        if self.status not in (QuoteStatus.DRAFT, QuoteStatus.SENT):
            raise InvalidQuoteStatusError(self.status, "accept")
        self._ensure_usable(item_count, today)
        self.status = QuoteStatus.ACCEPTED
        self.accepted_at = datetime.now()

    def expire(self, today: date) -> bool:
        """Marca vencida una abierta cuya fecha pasó (la tarea lo hace en SQL)"""
        if self.status in OPEN_QUOTE_STATUSES and self.valid_until < today:
            self.status = QuoteStatus.EXPIRED
            return True
        return False

    def renew(self, valid_until: date, today: date) -> None:
        """Una vencida vuelve a regir hasta `valid_until`: queda en borrador,
        emitida hoy, y sus líneas toman los precios de hoy (las del handler)"""
        if not self.is_expired(today):
            raise InvalidQuoteStatusError(self.status, "renew")
        self.issue_date = today
        self._ensure_validity(valid_until, today)
        self.valid_until = valid_until
        self.status = QuoteStatus.DRAFT
        self.sent_at = None
        self.accepted_at = None

    def ensure_convertible(self, today: date) -> None:
        """Se cobra mientras está abierta y rige; una vencida se renueva antes"""
        if self.status == QuoteStatus.CONVERTED:
            raise QuoteAlreadyConvertedError(self.number)
        if self.is_expired(today):
            raise QuoteExpiredError(self.number, self.valid_until)
        if self.status not in OPEN_QUOTE_STATUSES:
            raise InvalidQuoteStatusError(self.status, "convert")

    def convert(self, today: date) -> None:
        self.ensure_convertible(today)
        self.status = QuoteStatus.CONVERTED
        self.converted_at = datetime.now()

    def recalculate_totals(self, items: Iterable[QuoteItem]) -> None:
        """Como una venta sin descuento global: subtotal a centavos, IVA por
        tarifa redondeado por grupo y total = subtotal + IVA"""
        items = list(items)
        self.subtotal = round_money(sum((i.subtotal for i in items), Decimal("0")))
        breakdown = self.tax_breakdown(items)
        self.tax = sum((tax for _, tax in breakdown.values()), Decimal("0"))
        self.total = self.subtotal + self.tax

    @staticmethod
    def tax_breakdown(
        items: Iterable[QuoteItem],
    ) -> dict[TaxCode, tuple[Decimal, Decimal]]:
        """Base imponible e IVA por tarifa, a centavos"""
        return tax_breakdown(
            ((i.tax_code, i.subtotal, i.tax_amount) for i in items), Decimal("1")
        )

    def _ensure_usable(self, item_count: int, today: date) -> None:
        if item_count == 0:
            raise QuoteWithoutItemsError(self.number)
        if self.valid_until < today:
            raise QuoteExpiredError(self.number, self.valid_until)

    def _ensure_validity(self, valid_until: date, today: date) -> None:
        if valid_until < today or valid_until < self.issue_date:
            raise InvalidValueError(
                "A quote is valid until today or a later day, not "
                f"{valid_until.isoformat()}"
            )
