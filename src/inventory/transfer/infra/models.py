from datetime import datetime

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.infra.database import Base


class StockTransferModel(Base):
    __tablename__ = "stock_transfers"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_location_id: Mapped[int] = mapped_column(
        ForeignKey("locations.id"), index=True
    )
    destination_location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    status: Mapped[str] = mapped_column(default="draft")
    transfer_date: Mapped[datetime | None]
    requested_by: Mapped[str | None]
    notes: Mapped[str | None]
    created_at: Mapped[datetime | None] = mapped_column(default=datetime.now)


class StockTransferItemModel(Base):
    __tablename__ = "stock_transfer_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    transfer_id: Mapped[int] = mapped_column(
        ForeignKey("stock_transfers.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int]
    lot_id: Mapped[int | None] = mapped_column(
        ForeignKey("lots.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[str | None]
