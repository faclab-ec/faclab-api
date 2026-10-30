from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.infra.database import Base, TenantScoped


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
