from datetime import datetime
from decimal import Decimal

from pydantic import AliasChoices, BaseModel, Field

from src.purchasing.domain.entities import PurchaseOrderStatus
from src.shared.infra.validators import DecimalNumber, QueryParams


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
    subtotal: DecimalNumber
    tax: DecimalNumber
    total: DecimalNumber
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
    quantity_ordered: int = Field(
        ...,
        ge=1,
        description="Quantity ordered",
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


class PurchaseOrderItemUpdateRequest(BaseModel):
    quantity_ordered: int = Field(
        ...,
        ge=1,
        description="Quantity ordered",
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
    quantity_ordered: int = Field(
        validation_alias=AliasChoices("quantityOrdered", "quantity_ordered"),
        serialization_alias="quantityOrdered",
    )
    quantity_received: int = Field(
        validation_alias=AliasChoices("quantityReceived", "quantity_received"),
        serialization_alias="quantityReceived",
    )
    unit_cost: DecimalNumber = Field(
        validation_alias=AliasChoices("unitCost", "unit_cost"),
        serialization_alias="unitCost",
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
    quantity_received: int = Field(
        ...,
        ge=1,
        description="Quantity received",
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
