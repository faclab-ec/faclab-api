from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from src.data_protection.domain.entities import ExportStatus
from src.shared.infra.validators import QueryParams


class ExportResponse(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, from_attributes=True
    )

    id: int
    status: ExportStatus
    requested_by_name: str | None = Field(None, description="Who asked for it")
    file_size: int | None = Field(None, description="Bytes, once READY")
    tables: dict[str, int] = Field(
        default_factory=dict, description="Rows per table of the ZIP, once READY"
    )
    failure: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    expires_at: datetime | None = Field(
        None, description="After it the file is deleted: ask for another"
    )


class ExportQueryParams(QueryParams):
    pass
