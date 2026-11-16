"""Pydantic schemas for Shift validation and serialization."""

from datetime import datetime
from decimal import Decimal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from src.pos.shift.domain.entities import ShiftStatus
from src.sales.domain.entities import PaymentMethod
from src.shared.infra.validators import DecimalNumber, QueryParams


class OpenShiftRequest(BaseModel):
    """Open a new cashier shift. The cashier is the authenticated user."""

    opening_balance: Decimal = Field(
        ...,
        ge=0,
        description="Opening cash balance",
        validation_alias=AliasChoices("openingBalance", "opening_balance"),
        serialization_alias="openingBalance",
    )
    notes: str | None = Field(None, max_length=512, description="Additional notes")


class MethodCountRequest(BaseModel):
    """What the cashier counted of one payment method (S5.9)"""

    payment_method: PaymentMethod = Field(
        ...,
        description="Payment method counted (not CREDIT, which is owed, not in the till)",
        validation_alias=AliasChoices("paymentMethod", "payment_method"),
        serialization_alias="paymentMethod",
    )
    counted: Decimal = Field(
        ...,
        ge=0,
        description="Amount counted: the cash in the drawer, the card batch total, "
        "the transfers received",
    )
    justification: str | None = Field(
        None,
        max_length=512,
        description="Why counted and expected differ; required when the difference "
        "is over the threshold (SHIFT_CLOSING_JUSTIFICATION_THRESHOLD)",
    )


class CloseShiftRequest(BaseModel):
    """Close the shift with its count (S5.9): cash always, and every payment
    method the shift moved except CREDIT."""

    counts: list[MethodCountRequest] = Field(
        default_factory=list,
        description="The count of each payment method; CASH may come as closingBalance",
    )
    closing_balance: Decimal | None = Field(
        None,
        ge=0,
        description="Cash counted, when counts has no CASH line (clients before S5.9)",
        validation_alias=AliasChoices("closingBalance", "closing_balance"),
        serialization_alias="closingBalance",
    )
    notes: str | None = Field(None, max_length=512, description="Additional notes")


class ShiftResponse(BaseModel):
    """Shift details."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    cashier_name: str = Field(
        ...,
        validation_alias=AliasChoices("cashierName", "cashier_name"),
        serialization_alias="cashierName",
    )
    terminal_id: int | None = Field(
        None,
        description="POS terminal of the shift (null only before S2.6)",
        validation_alias=AliasChoices("terminalId", "terminal_id"),
        serialization_alias="terminalId",
    )
    branch_id: int | None = Field(
        None,
        description="Branch of the terminal",
        validation_alias=AliasChoices("branchId", "branch_id"),
        serialization_alias="branchId",
    )
    opened_by_user_id: int | None = Field(
        None,
        description="User who opened the shift",
        validation_alias=AliasChoices("openedByUserId", "opened_by_user_id"),
        serialization_alias="openedByUserId",
    )
    opened_at: datetime | None = Field(
        None,
        validation_alias=AliasChoices("openedAt", "opened_at"),
        serialization_alias="openedAt",
    )
    closed_at: datetime | None = Field(
        None,
        validation_alias=AliasChoices("closedAt", "closed_at"),
        serialization_alias="closedAt",
    )
    opening_balance: DecimalNumber = Field(
        ...,
        validation_alias=AliasChoices("openingBalance", "opening_balance"),
        serialization_alias="openingBalance",
    )
    closing_balance: DecimalNumber | None = Field(
        None,
        validation_alias=AliasChoices("closingBalance", "closing_balance"),
        serialization_alias="closingBalance",
    )
    expected_balance: DecimalNumber | None = Field(
        None,
        validation_alias=AliasChoices("expectedBalance", "expected_balance"),
        serialization_alias="expectedBalance",
    )
    discrepancy: DecimalNumber | None = Field(
        None,
        validation_alias=AliasChoices("discrepancy"),
    )
    status: ShiftStatus = Field(description="Current shift status")
    notes: str | None = None
    closed_by: str | None = Field(
        None,
        description="User who closed the shift",
        validation_alias=AliasChoices("closedBy", "closed_by"),
        serialization_alias="closedBy",
    )
    closing_number: str | None = Field(
        None,
        description="Number of its Z closing (S5.9); null while open or for a shift "
        "closed before S5.9",
        validation_alias=AliasChoices("closingNumber", "closing_number"),
        serialization_alias="closingNumber",
    )


class ShiftQueryParams(QueryParams):
    status: ShiftStatus | None = Field(None, description="Filter by shift status")
    branch_id: int | None = Field(
        None, ge=1, description="Filter by branch (one the user may enter)"
    )
    terminal_id: int | None = Field(None, ge=1, description="Filter by POS terminal")
