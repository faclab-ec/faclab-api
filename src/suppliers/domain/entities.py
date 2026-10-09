from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from src.shared.domain.entities import Entity
from src.shared.domain.tax import TaxType


@dataclass
class Supplier(Entity):
    name: str
    tax_id: str
    id: int | None = None
    tax_type: TaxType = TaxType.RUC
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    city: str | None = None
    country: str | None = None
    payment_terms: int | None = None  # Credit days
    lead_time_days: int | None = None
    is_active: bool = True
    notes: str | None = None
    created_at: datetime | None = None

    def activate(self) -> None:
        self.is_active = True

    def deactivate(self) -> None:
        self.is_active = False


@dataclass
class SupplierContact(Entity):
    supplier_id: int
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


@dataclass
class SupplierProduct(Entity):
    supplier_id: int
    product_id: int
    purchase_price: Decimal
    id: int | None = None
    supplier_sku: str | None = None
    min_order_quantity: int = 1
    lead_time_days: int | None = None
    is_preferred: bool = False

    def update(
        self,
        product_id: int,
        purchase_price: Decimal,
        supplier_sku: str | None = None,
        min_order_quantity: int = 1,
        lead_time_days: int | None = None,
        is_preferred: bool = False,
    ) -> None:
        self.product_id = product_id
        self.purchase_price = purchase_price
        self.supplier_sku = supplier_sku
        self.min_order_quantity = min_order_quantity
        self.lead_time_days = lead_time_days
        self.is_preferred = is_preferred
