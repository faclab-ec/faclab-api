from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from src.shared.infra.validators import QueryParams


class WarehouseRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    name: str = Field(description="Warehouse name")
    code: str = Field(description="Unique warehouse code (e.g. WH-001)")
    address: str | None = Field(None, description="Street address")
    city: str | None = Field(None, description="City")
    country: str | None = Field(None, description="Country")
    is_active: bool = Field(True, description="Whether the warehouse is active")
    is_default: bool = Field(False, description="Whether this is the default warehouse")
    manager: str | None = Field(None, description="Name of the warehouse manager")
    phone: str | None = Field(None, description="Contact phone number")
    email: str | None = Field(None, description="Contact email address")


class CreateWarehouseRequest(WarehouseRequest):
    branch_id: int = Field(
        ge=1, description="Branch of the warehouse; fixed once it is created"
    )


class WarehouseResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: int = Field(description="Warehouse ID")
    branch_id: int = Field(description="Branch of the warehouse")
    name: str = Field(description="Warehouse name")
    code: str = Field(description="Unique warehouse code")
    address: str | None = Field(None, description="Street address")
    city: str | None = Field(None, description="City")
    country: str | None = Field(None, description="Country")
    is_active: bool = Field(description="Whether the warehouse is active")
    is_default: bool = Field(description="Whether this is the default warehouse")
    manager: str | None = Field(None, description="Name of the warehouse manager")
    phone: str | None = Field(None, description="Contact phone number")
    email: str | None = Field(None, description="Contact email address")


class WarehouseQueryParams(QueryParams):
    branch_id: int | None = Field(None, ge=1, description="Filter by branch")
    is_active: bool | None = Field(None, description="Filter by active status")
