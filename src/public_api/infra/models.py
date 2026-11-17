from sqlalchemy import Double, String
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.infra.database import Base


class ApiRateLimitModel(Base):
    """The rate limit counter of a key of the public API (S6.3, D-6): an
    integration client (`client:<tenant>:<id>`) or a tenant (`tenant:<id>`).

    It keeps the GCRA's theoretical arrival time (`tat`, seconds since the
    epoch): when the bucket of the key is empty again. A row whose `tat` passed
    says nothing more than no row, so the worker purges them. A platform table
    without row-level security: the middleware checks it outside the request's
    transaction, before the route runs."""

    __tablename__ = "api_rate_limits"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    tat: Mapped[float] = mapped_column(Double, nullable=False)
