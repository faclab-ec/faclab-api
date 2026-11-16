from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from src.imports.domain.entities import (
    ImportKind,
    ImportMode,
    ImportRowAction,
    ImportStatus,
)
from src.shared.infra.validators import QueryParams


class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class SheetFormat(StrEnum):
    XLSX = "xlsx"
    CSV = "csv"


class ImportTemplateColumnResponse(_Camel):
    name: str = Field(description="The header in the file")
    description: str
    example: str
    key: bool = Field(description="Part of what identifies the record")
    required: bool = Field(
        description="Needed to create the record (a key one, in every row)"
    )


class ImportTemplateResponse(_Camel):
    kind: ImportKind
    file_name: str
    columns: list[ImportTemplateColumnResponse]


class ImportCountsResponse(_Camel):
    """Rows per action"""

    create: int = 0
    update: int = 0
    unchanged: int = 0
    skip: int = 0
    error: int = 0


def _counts(value: Any) -> Any:
    if isinstance(value, dict) and all(isinstance(k, str) for k in value):
        return {name.lower(): count for name, count in value.items()}
    return value


class ImportJobResponse(_Camel):
    id: int
    kind: ImportKind
    mode: ImportMode
    status: ImportStatus
    file_name: str
    file_size: int = Field(description="Bytes")
    total_rows: int
    processed_rows: int = Field(description="Rows the worker already executed")
    planned: ImportCountsResponse = Field(
        description="What each row would do, when the file was validated"
    )
    done: ImportCountsResponse = Field(description="What the worker did")
    user_name: str | None = Field(None, description="Who uploaded it")
    failed_row: int | None = Field(None, description="The row that stopped it")
    failure: str | None = None
    created_at: datetime | None = None
    confirmed_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    _planned = field_validator("planned", mode="before")(_counts)
    _done = field_validator("done", mode="before")(_counts)


class ImportRowErrorResponse(_Camel):
    column: str | None = Field(None, description="The template's header; none: the row")
    code: str
    message: str


class ImportRowResponse(_Camel):
    id: int
    row_number: int = Field(description="Its line in the sheet (the header is 1)")
    action: ImportRowAction
    errors: list[ImportRowErrorResponse] = Field(default_factory=list)
    data: dict[str, str | None] = Field(description="The row's cells by header")
    record_id: int | None = Field(None, description="What it created or updated")

    @field_validator("errors", mode="before")
    @classmethod
    def _no_errors(cls, value: Any) -> Any:
        return value or []


class ImportQueryParams(QueryParams):
    kind: ImportKind | None = None
    status: ImportStatus | None = None


class ImportRowQueryParams(QueryParams):
    action: ImportRowAction | None = Field(
        None, description="ERROR: only the rows with errors"
    )
