from src.public_api.infra.schemas.base import PublicModel


class EmissionPoint(PublicModel):
    id: int
    code: str
    name: str | None = None


class SaleLocation(PublicModel):
    """A location stock can leave from: a sale names it (`locationId`)"""

    id: int
    code: str
    name: str
    warehouse_id: int
    warehouse_code: str
    warehouse_name: str


class Branch(PublicModel):
    id: int
    code: str
    name: str
    address: str | None = None
    is_main: bool
    emission_points: list[EmissionPoint]
    locations: list[SaleLocation]
