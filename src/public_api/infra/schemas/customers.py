from enum import StrEnum

from pydantic import Field

from src.public_api.infra.schemas.base import PublicInput, PublicModel, SyncParams
from src.public_api.infra.types import Timestamp
from src.shared.domain.tax import TaxType


class IdentificationType(StrEnum):
    """The SRI's kind of identification of a customer"""

    RUC = "RUC"
    NATIONAL_ID = "NATIONAL_ID"
    PASSPORT = "PASSPORT"
    FOREIGN_ID = "FOREIGN_ID"

    @property
    def tax_type(self) -> TaxType:
        return TaxType[self.value]

    @classmethod
    def of(cls, tax_type: int) -> "IdentificationType":
        return cls(TaxType(tax_type).name)


class Customer(PublicModel):
    id: int
    name: str
    identification_type: IdentificationType
    identification: str
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    is_active: bool
    created_at: Timestamp
    updated_at: Timestamp


class CustomerInput(PublicInput):
    """Every editable field: a PUT replaces them all"""

    name: str = Field(min_length=1, max_length=128)
    identification_type: IdentificationType
    identification: str = Field(
        min_length=1,
        max_length=32,
        description="Validated as a RUC or cédula for those types",
    )
    email: str | None = Field(None, max_length=128)
    phone: str | None = Field(None, max_length=32)
    address: str | None = Field(None, max_length=255)
    city: str | None = Field(None, max_length=64)
    state: str | None = Field(None, max_length=64)
    country: str | None = Field(None, max_length=64)
    is_active: bool = True


class CustomerListParams(SyncParams):
    identification: str | None = Field(None, description="Exact RUC, cédula or id")
