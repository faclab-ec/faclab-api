from datetime import date

from pydantic import Field

from src.public_api.infra.schemas.base import Id, ListParams, PublicModel
from src.public_api.infra.types import Money, Quantity, Timestamp


class PriceList(PublicModel):
    id: int
    name: str
    description: str | None = None
    is_default: bool = Field(
        description="The general list: quantity tiers over the product's price"
    )
    is_active: bool
    valid_from: date | None = None
    valid_to: date | None = None
    created_at: Timestamp


class PriceListItem(PublicModel):
    id: int
    price_list_id: int
    product_id: int
    presentation_id: int
    min_quantity: Quantity = Field(
        description="From this quantity of the presentation on; 0 is its base price"
    )
    price: Money


class PriceListItemParams(ListParams):
    product_id: Id | None = None
