from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from src.inventory.location.domain.entities import LocationType
from src.shared.infra.validators import QueryParams


class LocationRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    warehouse_id: int = Field(description="ID of the parent warehouse")
    name: str = Field(description="Location name (e.g. Shelf A1)")
    code: str = Field(description="Unique location code within the warehouse")
    type: LocationType = Field(
        LocationType.STORAGE, description="Location type / purpose"
    )
    is_active: bool = Field(True, description="Whether the location is active")
    capacity: int | None = Field(
        None, ge=0, description="Maximum storage capacity in units"
    )


class LocationResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: int = Field(description="Location ID")
    warehouse_id: int = Field(description="ID of the parent warehouse")
    name: str = Field(description="Location name")
    code: str = Field(description="Unique location code")
    type: LocationType = Field(description="Location type / purpose")
    is_active: bool = Field(description="Whether the location is active")
    capacity: int | None = Field(None, description="Maximum storage capacity in units")


class LocationQueryParams(QueryParams):
    warehouse_id: int | None = Field(None, ge=1, description="Filter by warehouse ID")
    is_active: bool | None = Field(None, description="Filter by active status")
