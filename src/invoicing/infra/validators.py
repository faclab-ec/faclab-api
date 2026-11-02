from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from src.invoicing.domain.entities import (
    CreditNoteStatus,
    DiscrepancyKind,
    DiscrepancyStatus,
)
from src.sales.domain.entities import InvoiceStatus, SaleStatus
from src.shared.infra.validators import DecimalNumber, QueryParams


class CreditNoteResponse(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, from_attributes=True
    )

    id: int = Field(description="Credit note ID")
    status: CreditNoteStatus = Field(
        description="PENDING until faclab-invoicing reports the SRI's answer"
    )
    sale_id: int = Field(description="Sale whose invoice it modifies")
    refund_id: int | None = Field(
        None, description="Refund it backs; null for the invoice of a cancelled sale"
    )
    invoice_id: str = Field(description="Invoice it modifies, in faclab-invoicing")
    document_id: str | None = Field(
        None,
        description="Its last document with a result in faclab-invoicing: "
        "its XML and RIDE are downloaded with this id",
    )
    number: str | None = Field(
        None, description="Number of the document (001-001-000000012)"
    )
    access_code: str | None = Field(None, description="Access code of the document")
    reason: str = Field(description="Reason it carries (motivo)")
    total: DecimalNumber = Field(description="Amount it credits")
    authorized_at: datetime | None = Field(None, description="When the SRI authorized")
    rejection_reason: str | None = Field(None, description="Why it was rejected")
    requested_at: datetime | None = Field(None, description="When it was last asked")


class RequestCancelledSaleCreditNoteRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    reason: str = Field(
        min_length=1,
        max_length=300,
        description="Reason of the credit note (motivo, required by the SRI)",
    )


class DiscrepancySaleResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: int = Field(description="Sale ID")
    number: str | None = Field(None, description="Sale number (V-001-000123)")
    status: SaleStatus = Field(description="Sale status")
    total: DecimalNumber = Field(description="Sale total")
    branch_id: int | None = Field(None, description="Branch of the sale")
    customer_id: int | None = Field(
        None,
        description="Its customer; null is the final consumer, whose invoice "
        "admits no credit note",
    )
    sale_date: datetime | None = Field(None, description="When it was confirmed")
    invoice_status: InvoiceStatus | None = Field(
        None, description="Status of its invoice; null if it was never sent"
    )
    invoice_requested_at: datetime | None = Field(
        None, description="When it was last sent to faclab-invoicing"
    )


class InvoiceDiscrepancyResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: int = Field(description="Discrepancy ID")
    kind: DiscrepancyKind = Field(
        description="confirmed_without_result: confirmed and without an invoice "
        "result after the threshold (pending or never sent); "
        "authorized_on_cancelled: the SRI authorized the invoice of a cancelled sale"
    )
    status: DiscrepancyStatus = Field(
        description="open, reviewed (a user took it) or resolved (it went away)"
    )
    sale_id: int = Field(description="Sale ID")
    invoice_id: str | None = Field(
        None, description="Invoice in faclab-invoicing, when it reported one"
    )
    detected_at: datetime = Field(description="When it was detected")
    resolved_at: datetime | None = Field(None, description="When it went away")
    reviewed_at: datetime | None = Field(None, description="When it was reviewed")
    reviewed_by_name: str | None = Field(
        None, description="Who reviewed it (full name or username)"
    )
    review_note: str | None = Field(None, description="Note of the review")
    sale: DiscrepancySaleResponse | None = Field(
        None, description="The sale, as it is now"
    )
    credit_note: CreditNoteResponse | None = Field(
        None,
        description="The credit note of the invoice of a cancelled sale, once asked",
    )


class InvoiceDiscrepancyQueryParams(QueryParams):
    limit: int | None = Field(
        50, ge=1, le=500, description="Maximum records to return (1-500)"
    )
    status: DiscrepancyStatus | None = Field(
        DiscrepancyStatus.OPEN, description="Filter by status (open by default)"
    )
    kind: DiscrepancyKind | None = Field(None, description="Filter by kind")
    sale_id: int | None = Field(None, ge=1, description="Filter by sale ID")


class ReviewInvoiceDiscrepancyRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    note: str | None = Field(
        None, max_length=500, description="What was done or why it needs nothing"
    )
