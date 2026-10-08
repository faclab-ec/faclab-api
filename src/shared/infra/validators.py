from decimal import Decimal
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer
from pydantic.alias_generators import to_camel

DecimalNumber = Annotated[
    Decimal,
    PlainSerializer(lambda v: float(v), return_type=float),
]

T = TypeVar("T")


class QueryParams(BaseModel):
    """Base query parameters for paginated list endpoints."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    limit: int | None = Field(
        100, ge=1, le=1000, description="Maximum number of records to return (1-1000)"
    )
    offset: int | None = Field(
        0, ge=0, description="Number of records to skip for pagination"
    )


class Meta(BaseModel):
    """Metadata included in every API response."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    request_id: str = Field(description="Unique identifier for this request (UUID v4)")
    timestamp: str = Field(description="ISO 8601 timestamp of the response")

    def with_pagination(self, total: int, limit: int, offset: int) -> "PaginatedMeta":
        return PaginatedMeta(
            request_id=self.request_id,
            timestamp=self.timestamp,
            pagination=PaginationMeta(total=total, limit=limit, offset=offset),
        )


class PaginationMeta(BaseModel):
    """Pagination details returned in paginated list responses."""

    total: int = Field(description="Total number of records matching the query")
    limit: int = Field(description="Maximum records per page (as requested)")
    offset: int = Field(description="Number of records skipped (as requested)")


class PaginatedMeta(Meta):
    """Response metadata with pagination information."""

    pagination: PaginationMeta = Field(description="Pagination details")


class DataResponse(BaseModel, Generic[T]):
    """Standard wrapper for a single-resource response."""

    data: T = Field(description="The requested resource")
    meta: Meta = Field(description="Response metadata")


class ListResponse(BaseModel, Generic[T]):
    """Standard wrapper for a non-paginated list response."""

    data: list[T] = Field(description="List of resources")
    meta: Meta = Field(description="Response metadata")


class PaginatedDataResponse(BaseModel, Generic[T]):
    """Standard wrapper for a paginated list response."""

    data: list[T] = Field(description="List of resources for the current page")
    meta: PaginatedMeta = Field(
        description="Response metadata including pagination details"
    )


class ErrorDetail(BaseModel):
    """Individual error entry within an error response."""

    code: str = Field(
        description="Machine-readable error code (e.g. NOT_FOUND, DOMAIN_ERROR, VALIDATION_ERROR)"
    )
    message: str = Field(description="Human-readable error description")
    field: str | None = Field(
        None,
        description="Dot-path to the field that caused the error, if applicable",
    )
    detail: str | None = Field(
        None, description="Extra context for the error (e.g. the current status)"
    )


class ErrorResponse(BaseModel):
    """Standard error response returned by all endpoints on failure.

    Example:
    ```json
    {
      "errors": [
        {"code": "NOT_FOUND", "message": "Product with id 99 not found"}
      ],
      "meta": {
        "requestId": "550e8400-e29b-41d4-a716-446655440000",
        "timestamp": "2025-01-15T10:30:00Z"
      }
    }
    ```
    """

    errors: list[ErrorDetail] = Field(description="List of error details")
    meta: Meta = Field(description="Response metadata")


# ---------------------------------------------------------------------------
# Reusable OpenAPI error-response definitions
# ---------------------------------------------------------------------------

_ERR_400: dict = {
    "description": "**Business rule violation** — the request conflicts with domain rules (e.g. confirming an already-confirmed sale).",
    "model": ErrorResponse,
}
_ERR_404: dict = {
    "description": "**Resource not found** — the requested entity does not exist.",
    "model": ErrorResponse,
}
_ERR_409: dict = {
    "description": "**Conflict** — a unique value is already taken (`*_ALREADY_EXISTS`) or the resource is referenced by other records (`RECORD_IN_USE`).",
    "model": ErrorResponse,
}
_ERR_422: dict = {
    "description": "**Validation error** — the request body or query parameters failed validation.",
    "model": ErrorResponse,
}
_ERR_500: dict = {
    "description": "**Internal server error** — an unexpected error occurred.",
    "model": ErrorResponse,
}

RESPONSES_LIST: dict[int | str, dict] = {400: _ERR_400, 422: _ERR_422, 500: _ERR_500}
"""Error responses for list/search endpoints."""

RESPONSES_QUERY: dict[int | str, dict] = {
    400: _ERR_400,
    404: _ERR_404,
    422: _ERR_422,
    500: _ERR_500,
}
"""Error responses for single-resource GET endpoints."""

RESPONSES_COMMAND: dict[int | str, dict] = {
    400: _ERR_400,
    404: _ERR_404,
    409: _ERR_409,
    422: _ERR_422,
    500: _ERR_500,
}
"""Error responses for create/update/action endpoints."""

RESPONSES_DELETE: dict[int | str, dict] = {
    404: _ERR_404,
    409: _ERR_409,
    500: _ERR_500,
}
"""Error responses for delete endpoints."""
