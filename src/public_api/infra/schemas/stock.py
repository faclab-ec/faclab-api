from pydantic import Field

from src.public_api.infra.schemas.base import Id, PublicModel, SyncParams
from src.public_api.infra.types import Quantity, Timestamp


class StockRow(PublicModel):
    """A product in a location of the branch, in base units"""

    id: int
    product_id: int
    sku: str
    branch_id: int
    warehouse_id: int
    location_id: int
    quantity: Quantity
    reserved: Quantity = Field(description="Reserved by confirmed transfers")
    available: Quantity = Field(description="What a sale can take")
    updated_at: Timestamp


class StockParams(SyncParams):
    branch_id: Id | None = Field(
        None,
        description="Required unless the client may operate in a single branch",
    )
    product_id: Id | None = None
