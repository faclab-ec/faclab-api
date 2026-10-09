from pydantic import AliasChoices, BaseModel, Field

from src.shared.infra.validators import DecimalNumber, QueryParams


# Customer Requests
class CustomerRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128, description="Customer name")
    tax_id: str = Field(
        ...,
        min_length=1,
        max_length=32,
        description="Tax ID (RUC/NIT)",
        validation_alias=AliasChoices("taxId", "tax_id"),
        serialization_alias="taxId",
    )
    tax_type: int = Field(
        1,
        ge=1,
        le=4,
        description="Tax type: 1=RUC, 2=NATIONAL_ID, 3=PASSPORT, 4=FOREIGN_ID",
        validation_alias=AliasChoices(
            "taxType",
            "tax_type",
        ),
        serialization_alias="taxType",
    )
    email: str | None = Field(None, max_length=128)
    phone: str | None = Field(None, max_length=32)
    address: str | None = Field(None, max_length=255)
    city: str | None = Field(None, max_length=64)
    state: str | None = Field(None, max_length=64)
    country: str | None = Field(None, max_length=64)
    credit_limit: DecimalNumber | None = Field(
        None,
        ge=0,
        description="Credit limit",
        validation_alias=AliasChoices(
            "creditLimit",
            "credit_limit",
        ),
        serialization_alias="creditLimit",
    )
    payment_terms: int | None = Field(
        None,
        ge=0,
        description="Payment terms in days",
        validation_alias=AliasChoices(
            "paymentTerms",
            "payment_terms",
        ),
        serialization_alias="paymentTerms",
    )
    is_active: bool | None = Field(
        True,
        description="Customer active status",
        validation_alias=AliasChoices(
            "isActive",
            "is_active",
        ),
        serialization_alias="isActive",
    )


class CustomerContactRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128, description="Contact name")
    role: str | None = Field(None, max_length=64)
    email: str | None = Field(None, max_length=128)
    phone: str | None = Field(None, max_length=32)


# Customer Responses
class CustomerResponse(CustomerRequest):
    id: int = Field(ge=1, description="Customer ID")


class CustomerContactResponse(CustomerContactRequest):
    id: int = Field(ge=1, description="Contact ID")
    customer_id: int = Field(
        ge=1,
        description="Customer ID",
        validation_alias=AliasChoices("customerId", "customer_id"),
        serialization_alias="customerId",
    )


# Query Params
class CustomerQueryParams(QueryParams):
    search: str | None = Field(
        None,
        min_length=1,
        max_length=100,
        description="Text to look for in the name or tax ID (case-insensitive)",
    )
