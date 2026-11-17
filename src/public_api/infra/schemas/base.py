"""Base models of the public API's schemas (S6.3): camelCase, and never the
internal validators. A response model lists every field it sends: whatever
else the internal dicts carry is dropped. A request refuses unknown fields."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from src.public_api.app.listing import DEFAULT_LIMIT, MAX_LIMIT, PageRequest
from src.public_api.infra.types import utc_naive


class PublicModel(BaseModel):
    """A response: every field is always sent (null when it has no value), so
    the OpenAPI marks them all required and removing one is a breaking change"""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
        json_schema_serialization_defaults_required=True,
    )


class PublicInput(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid"
    )


Id = Annotated[int, Field(ge=1)]


class ListParams(BaseModel):
    """`limit` and `offset`, `sort` and `updatedSince`, common to every listing"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    limit: int = Field(
        DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Page size (1-200)"
    )
    offset: int = Field(0, ge=0, description="Rows to skip")
    sort: str | None = Field(
        None,
        description=(
            "One field of the resource's list, ascending or with a leading `-` "
            "descending. The id always breaks ties"
        ),
        examples=["-updatedAt"],
    )

    def page(self, updated_since: datetime | None = None) -> PageRequest:
        return PageRequest(
            limit=self.limit,
            offset=self.offset,
            sort=self.sort,
            updated_since=utc_naive(updated_since) if updated_since else None,
        )


class SyncParams(ListParams):
    updated_since: datetime | None = Field(
        None,
        description=(
            "Only the rows changed at or after this moment (ISO 8601). Without "
            "`sort` they come ordered by `updatedAt`, then id"
        ),
        examples=["2026-11-17T00:00:00Z"],
    )

    def page(self, updated_since: datetime | None = None) -> PageRequest:
        return super().page(updated_since or self.updated_since)
