"""Value types of the public API (S6.3, PUBLIC_API.md §4).

Money and quantities travel as decimal strings, never as binary floats:
`"12.50"`, `"2.5"`. A request may send them as a string or an integer; a JSON
number with a fraction is refused, since the client already lost precision
when it wrote it. Timestamps are ISO 8601 in UTC with `Z`.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BeforeValidator, Field, PlainSerializer, WithJsonSchema

from src.shared.infra.precision import QUANTITY_PRECISION, QUANTITY_SCALE

_CENTS = Decimal("0.01")
_DECIMAL_PATTERN = r"^\d+(\.\d{1,6})?$"


def money_text(value: Decimal) -> str:
    """At least two decimals, and the ones a line price keeps beyond them:
    `12.50`, `4.123456`"""
    normalized = value.normalize()
    exponent = normalized.as_tuple().exponent
    if not isinstance(exponent, int) or exponent > -2:
        return f"{value.quantize(_CENTS):f}"
    return f"{normalized:f}"


def quantity_text(value: Decimal) -> str:
    """Without trailing zeros nor exponent: `3`, `2.5`"""
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return f"{normalized.quantize(Decimal(1)):f}"
    return f"{normalized:f}"


def utc_text(value: datetime) -> str:
    """ISO 8601 in UTC with `Z`, in milliseconds (truncated: a sync that sends
    it back as `updatedSince` never skips the row). The server keeps its times
    in UTC without a zone."""
    if value.tzinfo is not None:
        value = value.astimezone(UTC)
    return value.replace(tzinfo=None).isoformat(timespec="milliseconds") + "Z"


def utc_naive(value: datetime) -> datetime:
    """A time of a request as the database keeps it: UTC without a zone"""
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _decimal_text(value: Any) -> Any:
    if isinstance(value, (bool, float)):
        raise ValueError('send decimals as a string ("12.50"), never as a JSON number')
    if isinstance(value, int):
        return Decimal(value)
    return value


def _schema(description: str, example: str) -> WithJsonSchema:
    return WithJsonSchema(
        {
            "type": "string",
            "pattern": _DECIMAL_PATTERN,
            "description": description,
            "examples": [example],
        }
    )


# Responses
Money = Annotated[
    Decimal,
    PlainSerializer(money_text, return_type=str),
    _schema("Amount in USD as a decimal string", "12.50"),
]
Quantity = Annotated[
    Decimal,
    PlainSerializer(quantity_text, return_type=str),
    _schema("Quantity as a decimal string", "2.5"),
]
Timestamp = Annotated[
    datetime,
    PlainSerializer(utc_text, return_type=str),
    WithJsonSchema(
        {
            "type": "string",
            "format": "date-time",
            "description": "ISO 8601 in UTC",
            "examples": ["2026-11-17T15:04:05.000Z"],
        }
    ),
]

# Requests
MoneyInput = Annotated[
    Decimal,
    BeforeValidator(_decimal_text),
    Field(ge=0, max_digits=QUANTITY_PRECISION, decimal_places=QUANTITY_SCALE),
    _schema("Amount in USD as a decimal string, up to 6 decimals", "12.50"),
]
QuantityInput = Annotated[
    Decimal,
    BeforeValidator(_decimal_text),
    Field(gt=0, max_digits=QUANTITY_PRECISION, decimal_places=QUANTITY_SCALE),
    _schema("Quantity as a decimal string, up to 6 decimals", "2.5"),
]
Percent = Annotated[
    Decimal,
    PlainSerializer(quantity_text, return_type=str),
    WithJsonSchema(
        {
            "type": "string",
            "pattern": _DECIMAL_PATTERN,
            "description": "Percentage as a decimal string (0-100)",
            "examples": ["10"],
        }
    ),
]
PercentInput = Annotated[
    Decimal,
    BeforeValidator(_decimal_text),
    Field(ge=0, le=100, max_digits=5, decimal_places=2),
    WithJsonSchema(
        {
            "type": "string",
            "pattern": r"^\d+(\.\d{1,2})?$",
            "description": "Percentage as a decimal string (0-100)",
            "examples": ["10"],
        }
    ),
]
