from dataclasses import dataclass
from datetime import datetime

from src.shared.domain.entities import Entity


@dataclass
class Warehouse(Entity):
    branch_id: int
    name: str
    code: str
    id: int | None = None
    address: str | None = None
    city: str | None = None
    country: str | None = None
    is_active: bool = True
    is_default: bool = False
    manager: str | None = None
    phone: str | None = None
    email: str | None = None
    created_at: datetime | None = None
