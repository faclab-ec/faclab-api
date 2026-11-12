from datetime import datetime
from decimal import Decimal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from src.purchasing.domain.entities import PurchaseOrderStatus, SupplierReturnStatus
from src.shared.domain.tax import TaxCode
from src.shared.infra.validators import DecimalNumber, QuantityNumber, QueryParams


class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class TaxRateResponse(_Camel):
    """Base imponible e IVA de una tarifa, a centavos (S5.7)"""

    tax_code: TaxCode
    rate: DecimalNumber = Field(description="VAT rate, a percentage (15)")
    base: DecimalNumber = Field(description="Taxable base of the rate")
    tax: DecimalNumber = Field(description="VAT of the rate")


# PurchaseOrder
class PurchaseOrderRequest(BaseModel):
    supplier_id: int = Field(
        ...,
        ge=1,
        description="Supplier ID",
        validation_alias=AliasChoices("supplierId", "supplier_id"),
        serialization_alias="supplierId",
    )
    notes: str | None = Field(None, max_length=1024)
    expected_date: datetime | None = Field(
        None,
        description="Expected delivery date",
        validation_alias=AliasChoices("expectedDate", "expected_date"),
        serialization_alias="expectedDate",
    )


class PurchaseOrderResponse(BaseModel):
    id: int = Field(ge=1)
    supplier_id: int = Field(
        ge=1,
        validation_alias=AliasChoices("supplierId", "supplier_id"),
        serialization_alias="supplierId",
    )
    supplier_name: str | None = Field(
        None,
        description="Supplier name",
        validation_alias=AliasChoices("supplierName", "supplier_name"),
        serialization_alias="supplierName",
    )
    order_number: str = Field(
        validation_alias=AliasChoices("orderNumber", "order_number"),
        serialization_alias="orderNumber",
    )
    status: PurchaseOrderStatus = Field(description="Current purchase order status")
    subtotal: DecimalNumber = Field(description="Sum of the lines, without VAT")
    tax: DecimalNumber = Field(
        description="VAT: each rate's lines grouped and rounded to cents (S5.7)"
    )
    total: DecimalNumber
    taxes: list[TaxRateResponse] | None = Field(
        None,
        description="Taxable base and VAT by rate, highest rate first; only in "
        "the order's detail",
    )
    notes: str | None = None
    expected_date: datetime | None = Field(
        None,
        validation_alias=AliasChoices("expectedDate", "expected_date"),
        serialization_alias="expectedDate",
    )
    created_at: datetime | None = Field(
        None,
        validation_alias=AliasChoices("createdAt", "created_at"),
        serialization_alias="createdAt",
    )
    updated_at: datetime | None = Field(
        None,
        validation_alias=AliasChoices("updatedAt", "updated_at"),
        serialization_alias="updatedAt",
    )


# PurchaseOrderItem
class PurchaseOrderItemRequest(BaseModel):
    purchase_order_id: int = Field(
        ...,
        ge=1,
        description="Purchase order ID",
        validation_alias=AliasChoices("purchaseOrderId", "purchase_order_id"),
        serialization_alias="purchaseOrderId",
    )
    product_id: int = Field(
        ...,
        ge=1,
        description="Product ID",
        validation_alias=AliasChoices("productId", "product_id"),
        serialization_alias="productId",
    )
    presentation_id: int | None = Field(
        None,
        ge=1,
        description="Presentation it is bought in (box of 100); none: the base "
        "unit. Its receipts put quantity × its factor into stock",
        validation_alias=AliasChoices("presentationId", "presentation_id"),
        serialization_alias="presentationId",
    )
    quantity_ordered: QuantityNumber = Field(
        ...,
        gt=0,
        description="Quantity ordered in its presentation: the decimals of the "
        "product's unit minus those of the presentation's factor",
        validation_alias=AliasChoices("quantityOrdered", "quantity_ordered"),
        serialization_alias="quantityOrdered",
    )
    unit_cost: Decimal = Field(
        ...,
        ge=0,
        description="Cost of one unit of its presentation (one box)",
        validation_alias=AliasChoices("unitCost", "unit_cost"),
        serialization_alias="unitCost",
    )


class PurchaseOrderItemUpdateRequest(BaseModel):
    quantity_ordered: QuantityNumber = Field(
        ...,
        gt=0,
        description="Quantity ordered, with the decimals of the product's unit",
        validation_alias=AliasChoices("quantityOrdered", "quantity_ordered"),
        serialization_alias="quantityOrdered",
    )
    unit_cost: Decimal = Field(
        ...,
        ge=0,
        description="Unit cost",
        validation_alias=AliasChoices("unitCost", "unit_cost"),
        serialization_alias="unitCost",
    )


class PurchaseOrderItemResponse(BaseModel):
    id: int = Field(ge=1)
    purchase_order_id: int = Field(
        ge=1,
        validation_alias=AliasChoices("purchaseOrderId", "purchase_order_id"),
        serialization_alias="purchaseOrderId",
    )
    product_id: int = Field(
        ge=1,
        validation_alias=AliasChoices("productId", "product_id"),
        serialization_alias="productId",
    )
    product_name: str | None = Field(
        None,
        description="Product name",
        validation_alias=AliasChoices("productName", "product_name"),
        serialization_alias="productName",
    )
    product_sku: str | None = Field(
        None,
        description="Product SKU",
        validation_alias=AliasChoices("productSku", "product_sku"),
        serialization_alias="productSku",
    )
    quantity_ordered: QuantityNumber = Field(
        validation_alias=AliasChoices("quantityOrdered", "quantity_ordered"),
        serialization_alias="quantityOrdered",
    )
    quantity_received: QuantityNumber = Field(
        validation_alias=AliasChoices("quantityReceived", "quantity_received"),
        serialization_alias="quantityReceived",
    )
    unit_cost: DecimalNumber = Field(
        validation_alias=AliasChoices("unitCost", "unit_cost"),
        serialization_alias="unitCost",
    )
    presentation_id: int | None = Field(
        None,
        description="Presentation it is bought in (null before S5.2: the base unit)",
        validation_alias=AliasChoices("presentationId", "presentation_id"),
        serialization_alias="presentationId",
    )
    presentation_name: str | None = Field(
        None,
        description="Name of its presentation (Caja x100)",
        validation_alias=AliasChoices("presentationName", "presentation_name"),
        serialization_alias="presentationName",
    )
    unit_factor: QuantityNumber = Field(
        Decimal(1),
        description="Base units in one of its presentation: ordered, received and "
        "pending are in the presentation",
        validation_alias=AliasChoices("unitFactor", "unit_factor"),
        serialization_alias="unitFactor",
    )
    quantity_returned: QuantityNumber = Field(
        Decimal(0),
        description="Quantity given back to the supplier, in its presentation (S5.7)",
        validation_alias=AliasChoices("quantityReturned", "quantity_returned"),
        serialization_alias="quantityReturned",
    )
    tax_code: TaxCode = Field(
        TaxCode.VAT_15,
        description="The product's VAT code when the line was added (S5.7)",
        validation_alias=AliasChoices("taxCode", "tax_code"),
        serialization_alias="taxCode",
    )
    subtotal: DecimalNumber = Field(
        Decimal(0),
        description="Quantity ordered × unit cost, without VAT, at full precision",
    )
    tax_amount: DecimalNumber = Field(
        Decimal(0),
        description="The line's VAT at full precision; the order rounds each rate",
        validation_alias=AliasChoices("taxAmount", "tax_amount"),
        serialization_alias="taxAmount",
    )


# PurchaseReceipt
class ReceiveItemRequest(BaseModel):
    purchase_order_item_id: int = Field(
        ...,
        ge=1,
        description="Purchase order item ID",
        validation_alias=AliasChoices("purchaseOrderItemId", "purchase_order_item_id"),
        serialization_alias="purchaseOrderItemId",
    )
    quantity_received: QuantityNumber = Field(
        ...,
        gt=0,
        description="Quantity received, with the decimals of the product's unit",
        validation_alias=AliasChoices("quantityReceived", "quantity_received"),
        serialization_alias="quantityReceived",
    )
    location_id: int | None = Field(
        None,
        ge=1,
        description="Storage location ID",
        validation_alias=AliasChoices("locationId", "location_id"),
        serialization_alias="locationId",
    )
    lot_number: str | None = Field(
        None,
        max_length=64,
        description="Lot number for traceability",
        validation_alias=AliasChoices("lotNumber", "lot_number"),
        serialization_alias="lotNumber",
    )
    serial_numbers: list[str] | None = Field(
        None,
        description="Serial numbers for individual unit tracking",
        validation_alias=AliasChoices("serialNumbers", "serial_numbers"),
        serialization_alias="serialNumbers",
    )


class CreatePurchaseReceiptRequest(BaseModel):
    items: list[ReceiveItemRequest] = Field(
        ..., min_length=1, description="Items received"
    )
    notes: str | None = Field(None, max_length=1024)
    received_at: datetime | None = Field(
        None,
        description="Date/time of receipt",
        validation_alias=AliasChoices("receivedAt", "received_at"),
        serialization_alias="receivedAt",
    )
    supplier_invoice_number: str | None = Field(
        None,
        max_length=20,
        description="The supplier's invoice for this delivery (001-001-000000123); "
        "its account payable carries it (S5.7)",
        validation_alias=AliasChoices(
            "supplierInvoiceNumber", "supplier_invoice_number"
        ),
        serialization_alias="supplierInvoiceNumber",
    )


class PurchaseReceiptResponse(BaseModel):
    id: int = Field(ge=1)
    purchase_order_id: int = Field(
        ge=1,
        validation_alias=AliasChoices("purchaseOrderId", "purchase_order_id"),
        serialization_alias="purchaseOrderId",
    )
    notes: str | None = None
    received_at: datetime | None = Field(
        None,
        validation_alias=AliasChoices("receivedAt", "received_at"),
        serialization_alias="receivedAt",
    )
    supplier_invoice_number: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "supplierInvoiceNumber", "supplier_invoice_number"
        ),
        serialization_alias="supplierInvoiceNumber",
    )
    subtotal: DecimalNumber = Field(
        Decimal(0), description="What was received at the lines' costs, without VAT"
    )
    tax: DecimalNumber = Field(Decimal(0), description="Its VAT, by rate")
    total: DecimalNumber = Field(
        Decimal(0), description="What is owed for it: its account payable (S5.7)"
    )
    created_at: datetime | None = Field(
        None,
        validation_alias=AliasChoices("createdAt", "created_at"),
        serialization_alias="createdAt",
    )


# Query Params
class PurchaseOrderQueryParams(QueryParams):
    status: PurchaseOrderStatus | None = Field(
        None, description="Filter by order status"
    )
    supplier_id: int | None = Field(None, ge=1)


# Supplier returns (S5.7)
class CreateSupplierReturnRequest(_Camel):
    purchase_order_id: int = Field(
        ge=1, description="The order whose received goods go back"
    )
    notes: str | None = Field(None, max_length=1024)


class UpdateSupplierReturnRequest(_Camel):
    notes: str | None = Field(None, max_length=1024)


class ConfirmSupplierReturnRequest(_Camel):
    supplier_credit_note_number: str | None = Field(
        None,
        max_length=20,
        description="The supplier's credit note for it, when there is one",
    )


class AddSupplierReturnItemRequest(_Camel):
    purchase_order_item_id: int = Field(
        ge=1, description="A line of the return's order with goods received"
    )
    quantity: QuantityNumber = Field(
        gt=0,
        description="Quantity in the line's presentation: at most what it received "
        "minus what went back",
    )
    location_id: int | None = Field(
        None, ge=1, description="Where it leaves from; none: the stock without location"
    )


class UpdateSupplierReturnItemRequest(_Camel):
    quantity: QuantityNumber = Field(gt=0)
    location_id: int | None = Field(None, ge=1)


class SupplierReturnResponse(_Camel):
    id: int
    number: str | None = Field(None, description="`DP-2026-0001`")
    supplier_id: int
    supplier_name: str | None = None
    purchase_order_id: int
    order_number: str | None = None
    status: SupplierReturnStatus
    notes: str | None = None
    supplier_credit_note_number: str | None = None
    subtotal: DecimalNumber = Field(description="Sum of the lines, without VAT")
    tax: DecimalNumber = Field(description="VAT, by rate")
    total: DecimalNumber = Field(description="What the supplier credits")
    credited_amount: DecimalNumber = Field(
        description="What it took off the supplier's accounts payable when confirmed"
    )
    refund_due: DecimalNumber = Field(
        description="What the supplier has to refund: it had already been paid"
    )
    taxes: list[TaxRateResponse] | None = Field(
        None, description="Taxable base and VAT by rate; only in the detail"
    )
    confirmed_at: datetime | None = None
    confirmed_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SupplierReturnItemResponse(_Camel):
    id: int
    supplier_return_id: int
    purchase_order_item_id: int
    product_id: int
    product_name: str | None = None
    product_sku: str | None = None
    presentation_id: int | None = None
    presentation_name: str | None = None
    unit_factor: QuantityNumber
    quantity: QuantityNumber = Field(description="In the line's presentation")
    base_quantity: QuantityNumber = Field(description="What leaves the stock")
    unit_cost: DecimalNumber = Field(description="The order line's cost")
    tax_code: TaxCode
    subtotal: DecimalNumber
    tax_amount: DecimalNumber
    location_id: int | None = None


class SupplierReturnQueryParams(QueryParams):
    supplier_id: int | None = Field(None, ge=1)
    purchase_order_id: int | None = Field(None, ge=1)
    status: SupplierReturnStatus | None = None
