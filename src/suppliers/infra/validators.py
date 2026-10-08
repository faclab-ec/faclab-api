from pydantic import AliasChoices, BaseModel, Field

from src.shared.infra.validators import DecimalNumber, QueryParams


# Supplier Requests
class SupplierRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128, description="Supplier name")
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
        validation_alias=AliasChoices("taxType", "tax_type"),
        serialization_alias="taxType",
    )
    email: str | None = Field(None, max_length=128)
    phone: str | None = Field(None, max_length=32)
    address: str | None = Field(None, max_length=255)
    city: str | None = Field(None, max_length=64)
    country: str | None = Field(None, max_length=64)
    payment_terms: int | None = Field(
        None,
        ge=0,
        description="Payment terms in days",
        validation_alias=AliasChoices("paymentTerms", "payment_terms"),
        serialization_alias="paymentTerms",
    )
    lead_time_days: int | None = Field(
        None,
        ge=0,
        description="Lead time in days",
        validation_alias=AliasChoices("leadTimeDays", "lead_time_days"),
        serialization_alias="leadTimeDays",
    )
    is_active: bool | None = Field(
        True,
        description="Supplier active status",
        validation_alias=AliasChoices("isActive", "is_active"),
        serialization_alias="isActive",
    )
    notes: str | None = Field(None, max_length=512)


class SupplierResponse(SupplierRequest):
    id: int = Field(ge=1, description="Supplier ID")


# SupplierContact Requests
class SupplierContactRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128, description="Contact name")
    role: str | None = Field(None, max_length=64)
    email: str | None = Field(None, max_length=128)
    phone: str | None = Field(None, max_length=32)


class SupplierContactResponse(SupplierContactRequest):
    id: int = Field(ge=1, description="Contact ID")
    supplier_id: int = Field(
        ge=1,
        description="Supplier ID",
        validation_alias=AliasChoices("supplierId", "supplier_id"),
        serialization_alias="supplierId",
    )


# SupplierProduct Requests
class SupplierProductRequest(BaseModel):
    product_id: int = Field(
        ...,
        ge=1,
        description="Product ID",
        validation_alias=AliasChoices("productId", "product_id"),
        serialization_alias="productId",
    )
    purchase_price: DecimalNumber = Field(
        ...,
        ge=0,
        description="Purchase price",
        validation_alias=AliasChoices("purchasePrice", "purchase_price"),
        serialization_alias="purchasePrice",
    )
    supplier_sku: str | None = Field(
        None,
        max_length=64,
        description="Supplier SKU",
        validation_alias=AliasChoices("supplierSku", "supplier_sku"),
        serialization_alias="supplierSku",
    )
    min_order_quantity: int = Field(
        1,
        ge=1,
        description="Minimum order quantity",
        validation_alias=AliasChoices("minOrderQuantity", "min_order_quantity"),
        serialization_alias="minOrderQuantity",
    )
    lead_time_days: int | None = Field(
        None,
        ge=0,
        description="Lead time in days",
        validation_alias=AliasChoices("leadTimeDays", "lead_time_days"),
        serialization_alias="leadTimeDays",
    )
    is_preferred: bool = Field(
        False,
        description="Is preferred supplier for this product",
        validation_alias=AliasChoices("isPreferred", "is_preferred"),
        serialization_alias="isPreferred",
    )


class SupplierProductResponse(SupplierProductRequest):
    id: int = Field(ge=1, description="Supplier product ID")
    supplier_id: int = Field(
        ...,
        ge=1,
        description="Supplier ID",
        validation_alias=AliasChoices("supplierId", "supplier_id"),
        serialization_alias="supplierId",
    )


# Query Params
class SupplierQueryParams(QueryParams):
    is_active: bool | None = None
