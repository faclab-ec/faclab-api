"""Pydantic schemas for Shift validation and serialization."""

from datetime import datetime
from decimal import Decimal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from src.pos.shift.domain.entities import ShiftStatus
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


class CloseShiftRequest(BaseModel):
    """Close the current shift."""

    closing_balance: Decimal = Field(
        ...,
        ge=0,
        description="Actual closing cash balance (counted)",
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


class ShiftQueryParams(QueryParams):
    status: ShiftStatus | None = Field(None, description="Filter by shift status")
