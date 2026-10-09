from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from src.shared.domain.entities import Entity
from src.shared.domain.tax import TaxType


@dataclass
class Customer(Entity):
    name: str
    tax_id: str
    tax_type: TaxType = TaxType.RUC
    id: int | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    credit_limit: Decimal | None = None
    payment_terms: int | None = None  # Days
    is_active: bool = True
    created_at: datetime | None = None

    def activate(self) -> None:
        self.is_active = True

    def deactivate(self) -> None:
        self.is_active = False


@dataclass
class CustomerContact(Entity):
    customer_id: int
    name: str
    id: int | None = None
    role: str | None = None
    email: str | None = None
    phone: str | None = None

    def update(
        self,
        name: str,
        role: str | None = None,
        email: str | None = None,
        phone: str | None = None,
    ) -> None:
        self.name = name
        self.role = role
        self.email = email
        self.phone = phone
