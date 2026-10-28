from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.infra.database import Base


class DeadLetterStatus(StrEnum):
    PENDING = "pending"
    REPROCESSED = "reprocessed"


class DeadLetterModel(Base):
    """Mensaje de Kafka que el consumidor no pudo procesar tras agotar sus
    reintentos. Se guarda con sus headers y el error, se confirma su offset para
    que la partición siga, y queda para reprocesarlo a mano
    (`python -m src.background.cli dead-letter-reprocess`).

    Infraestructura, como el outbox: la escribe y la lee faclab_worker en todas
    las empresas. `tenant_id` es la empresa del mensaje, si traía una.
    """

    __tablename__ = "dead_letters"
    __table_args__ = (
        # A message redelivered after its offset commit failed is kept once
        UniqueConstraint(
            "consumer_group",
            "topic",
            "kafka_partition",
            "kafka_offset",
            name="uq_dead_letters_message",
        ),
        Index(
            "ix_dead_letters_pending",
            "id",
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    consumer_group: Mapped[str] = mapped_column(String(128), nullable=False)
    topic: Mapped[str] = mapped_column(String(128), nullable=False)
    kafka_partition: Mapped[int] = mapped_column(nullable=False)
    kafka_offset: Mapped[int] = mapped_column(BigInteger, nullable=False)
    key: Mapped[str | None] = mapped_column(String(255))
    tenant_id: Mapped[UUID | None] = mapped_column(Uuid)
    headers: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    # The message as it arrived, decoded as UTF-8
    value: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=DeadLetterStatus.PENDING.value
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    # Who processed it again, and when
    reprocessed_at: Mapped[datetime | None] = mapped_column(DateTime)
    reprocessed_by: Mapped[str | None] = mapped_column(String(64))
