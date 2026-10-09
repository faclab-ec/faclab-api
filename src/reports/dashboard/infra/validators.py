from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from src.reports.inventory.infra.validators import WarehouseSummaryResponse
from src.shared.infra.validators import DecimalNumber


class DashboardAlertsResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    low_stock: int = Field(description="Products below their minimum stock")
    out_of_stock: int = Field(description="Products with no stock")
    reorder_point: int = Field(description="Products at or below the reorder point")
    expiring_soon: int = Field(description="Lots expiring within `expiringDays`")


class DashboardResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    inventory_value: DecimalNumber = Field(description="Current inventory value")
    warehouses: list[WarehouseSummaryResponse]
    alerts: DashboardAlertsResponse
    uninvoiced_sales: int = Field(
        description="Confirmed sales whose invoice the SRI hasn't authorized yet"
    )


class DashboardQueryParams(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    expiring_days: int = Field(
        30, ge=1, le=365, description="Days ahead to count lots as expiring"
    )
