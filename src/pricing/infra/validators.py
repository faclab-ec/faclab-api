from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from src.shared.infra.validators import DecimalNumber, QuantityNumber, QueryParams


class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class PriceListRequest(_Camel):
    """A price list (S5.3): retail, wholesale, by volume"""

    name: str = Field(min_length=1, max_length=64, description="Wholesale, Retail")
    description: str | None = Field(None, max_length=255)
    is_active: bool = Field(True, description="An inactive list doesn't price any sale")
    valid_from: date | None = Field(
        None, description="First day the list applies (none: since always)"
    )
    valid_to: date | None = Field(
        None, description="Last day the list applies (none: with no end)"
    )


class PriceListResponse(PriceListRequest):
    id: int = Field(ge=1, description="Price list ID")
    is_default: bool = Field(
        description="The company's general list: always active, without validity "
        "dates, its base price is the product's and it only holds quantity tiers"
    )


class PriceListQueryParams(QueryParams):
    is_active: bool | None = Field(None, description="Filter by active status")


class PriceListItemUpdateRequest(_Camel):
    price: DecimalNumber = Field(
        ge=0, description="Price of one unit of the presentation"
    )
    min_quantity: QuantityNumber = Field(
        default=Decimal(0),
        ge=0,
        description="From what quantity in the presentation it applies: 0 is the "
        "list's base price, more is a volume tier. Above 0 in the general list",
    )


class PriceListItemRequest(PriceListItemUpdateRequest):
    product_id: int = Field(ge=1, description="Product ID")
    presentation_id: int | None = Field(
        None,
        ge=1,
        description="Presentation it prices (none: the product's base unit). A "
        "presentation without its own item takes the base unit's × its factor",
    )


class PriceListItemResponse(_Camel):
    id: int = Field(ge=1, description="Item ID")
    price_list_id: int = Field(ge=1, description="Price list ID")
    product_id: int = Field(ge=1, description="Product ID")
    presentation_id: int = Field(ge=1, description="Presentation ID")
    price: DecimalNumber
    min_quantity: QuantityNumber
    product_name: str | None = None
    product_sku: str | None = None
    presentation_name: str | None = None
    unit_factor: QuantityNumber | None = Field(
        None, description="Base units in one of the presentation"
    )
    is_base_presentation: bool = Field(
        description="Whether it prices the product's base unit"
    )


class PriceListItemQueryParams(QueryParams):
    product_id: int | None = Field(None, ge=1, description="Filter by product")


class PriceLineRequest(_Camel):
    product_id: int = Field(ge=1)
    presentation_id: int | None = Field(
        None, ge=1, description="Presentation it is sold in (none: the base unit)"
    )
    quantity: QuantityNumber = Field(gt=0, description="Quantity in the presentation")


class ResolvePricesRequest(_Camel):
    customer_id: int | None = Field(
        None, ge=1, description="Customer of the sale (none: final consumer)"
    )
    items: list[PriceLineRequest] = Field(min_length=1, max_length=500)


class ResolvedPriceResponse(_Camel):
    product_id: int
    presentation_id: int | None
    quantity: QuantityNumber
    unit_price: DecimalNumber | None = Field(
        description="Price of one unit of the presentation the sale takes (null "
        "when neither a list nor the product has one)"
    )
    price_list_id: int | None = Field(
        description="List that gave the price (null: the product's, the general "
        "list's base price)"
    )
    price_list_name: str | None
    min_quantity: QuantityNumber | None = Field(
        description="From what quantity the list's price applies"
    )
