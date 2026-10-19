from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from src.shared.infra.validators import QueryParams

_SRI_CODE = r"^\d{3}$"


class BranchRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    establishment_code: str = Field(
        pattern=_SRI_CODE,
        description="SRI establishment code, three digits from 001 to 999",
    )
    name: str = Field(min_length=1, max_length=128, description="Branch name")
    address: str | None = Field(
        None, max_length=300, description="Establishment address"
    )
    is_active: bool = Field(True, description="Whether the branch is active")


class BranchResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: int = Field(description="Branch ID")
    establishment_code: str = Field(description="SRI establishment code")
    name: str = Field(description="Branch name")
    address: str | None = Field(None, description="Establishment address")
    is_main: bool = Field(
        description="Whether this is the main branch (matriz), set at provisioning"
    )
    is_active: bool = Field(description="Whether the branch is active")


class BranchQueryParams(QueryParams):
    is_active: bool | None = Field(None, description="Filter by active status")


class CreateEmissionPointRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    branch_id: int = Field(ge=1, description="Branch of the emission point")
    code: str = Field(
        pattern=_SRI_CODE,
        description="SRI emission point code, three digits from 001 to 999",
    )
    name: str | None = Field(None, max_length=128, description="Display name")
    is_active: bool = Field(True, description="Whether the emission point is active")


class UpdateEmissionPointRequest(BaseModel):
    """The branch of an emission point is fixed when it is created"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    code: str = Field(
        pattern=_SRI_CODE,
        description="SRI emission point code, three digits from 001 to 999",
    )
    name: str | None = Field(None, max_length=128, description="Display name")
    is_active: bool = Field(True, description="Whether the emission point is active")


class EmissionPointResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: int = Field(description="Emission point ID")
    branch_id: int = Field(description="Branch of the emission point")
    code: str = Field(description="SRI emission point code")
    name: str | None = Field(None, description="Display name")
    is_active: bool = Field(description="Whether the emission point is active")


class EmissionPointQueryParams(QueryParams):
    branch_id: int | None = Field(None, ge=1, description="Filter by branch")
    is_active: bool | None = Field(None, description="Filter by active status")


class CreatePosTerminalRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    branch_id: int = Field(ge=1, description="Branch of the terminal")
    emission_point_id: int = Field(
        ge=1, description="Emission point of the same branch the terminal issues by"
    )
    default_location_id: int = Field(
        ge=1,
        description=(
            "Location the terminal takes stock from, in a warehouse of the same branch"
        ),
    )
    code: str = Field(
        min_length=1, max_length=32, description="Code, unique in the branch"
    )
    name: str = Field(min_length=1, max_length=128, description="Display name")
    is_active: bool = Field(True, description="Whether the terminal is active")


class UpdatePosTerminalRequest(BaseModel):
    """The branch of a terminal is fixed when it is created"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    emission_point_id: int = Field(
        ge=1, description="Emission point of the same branch the terminal issues by"
    )
    default_location_id: int = Field(
        ge=1,
        description=(
            "Location the terminal takes stock from, in a warehouse of the same branch"
        ),
    )
    code: str = Field(
        min_length=1, max_length=32, description="Code, unique in the branch"
    )
    name: str = Field(min_length=1, max_length=128, description="Display name")
    is_active: bool = Field(True, description="Whether the terminal is active")


class PosTerminalResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: int = Field(description="Terminal ID")
    branch_id: int = Field(description="Branch of the terminal")
    emission_point_id: int = Field(description="Emission point it issues by")
    default_location_id: int = Field(description="Location it takes stock from")
    code: str = Field(description="Code, unique in the branch")
    name: str = Field(description="Display name")
    is_active: bool = Field(description="Whether the terminal is active")


class PosTerminalQueryParams(QueryParams):
    branch_id: int | None = Field(None, ge=1, description="Filter by branch")
    is_active: bool | None = Field(None, description="Filter by active status")
