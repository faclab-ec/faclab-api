from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.infra.database import Base, TenantScoped
from src.shared.infra.precision import MoneyColumn


class InvoiceDiscrepancyModel(TenantScoped, Base):
    """A sale that doesn't square with faclab-invoicing (S4.3): its invoice had
    no result in time, or the SRI authorized it after the sale was cancelled.

    Written by the worker's reconciliation and by the `invoices` consumer, never
    from a request body, so the sale's key is internal (the sale loaded by id).
    """

    __tablename__ = "invoice_discrepancies"
    __table_args__ = (
        # One unresolved per sale and kind: a reviewed one isn't opened again
        # while the condition lasts, and two workers can't open it twice
        Index(
            "uq_invoice_discrepancies_tenant_sale_kind_unresolved",
            "tenant_id",
            "sale_id",
            "kind",
            unique=True,
            postgresql_where=text("status <> 'resolved'"),
            sqlite_where=text("status <> 'resolved'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sale_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sales.id"), nullable=False, index=True
    )
    # DiscrepancyKind and DiscrepancyStatus
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="open", index=True
    )
    invoice_id: Mapped[str | None] = mapped_column(String(64))
    detected_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    # The token's user; the name is the full name or username at the time
    reviewed_by_id: Mapped[int | None] = mapped_column(Integer)
    reviewed_by_name: Mapped[str | None] = mapped_column(String(64))
    review_note: Mapped[str | None] = mapped_column(String(500))


class CreditNoteModel(TenantScoped, Base):
    """A credit note asked of faclab-invoicing (S4.5) and its result. Never from a
    request body: the sale and the refund are the ones loaded by id."""

    __tablename__ = "credit_notes"
    __table_args__ = (
        # A refund has one credit note, and so does the invoice of a cancelled
        # sale; asking again uses the same row
        Index(
            "uq_credit_notes_tenant_refund",
            "tenant_id",
            "refund_id",
            unique=True,
            postgresql_where=text("refund_id IS NOT NULL"),
            sqlite_where=text("refund_id IS NOT NULL"),
        ),
        Index(
            "uq_credit_notes_tenant_cancelled_sale",
            "tenant_id",
            "sale_id",
            unique=True,
            postgresql_where=text("refund_id IS NULL"),
            sqlite_where=text("refund_id IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sale_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sales.id"), nullable=False, index=True
    )
    refund_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("pos_refunds.id"), nullable=True, index=True
    )
    # The invoice it modifies and the last document with a result, in invoicing
    invoice_id: Mapped[str] = mapped_column(String(64), nullable=False)
    document_id: Mapped[str | None] = mapped_column(String(64))
    # CreditNoteStatus
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="PENDING", index=True
    )
    reason: Mapped[str] = mapped_column(String(512), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)
    tax: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)
    total: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)
    number: Mapped[str | None] = mapped_column(String(32))
    access_code: Mapped[str | None] = mapped_column(String(49))
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime)
    rejection_reason: Mapped[str | None] = mapped_column(String(1000))
    requested_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
