from fastapi import APIRouter, Depends
from wireup import Injected

from src.auth.domain.permissions import Permission
from src.auth.infra.dependencies import require_permission
from src.pos.reports.app.queries.by_payment_method import (
    GetSalesByPaymentMethodQuery,
    GetSalesByPaymentMethodQueryHandler,
)
from src.pos.reports.app.queries.daily_summary import (
    GetDailySummaryQuery,
    GetDailySummaryQueryHandler,
)
from src.pos.reports.app.queries.x_report import GetXReportQuery, GetXReportQueryHandler
from src.pos.reports.app.queries.z_report import GetZReportQuery, GetZReportQueryHandler
from src.pos.reports.infra.validators import (
    ByPaymentMethodQueryParams,
    DailySummaryQueryParams,
    DailySummaryResponse,
    PaymentMethodSummaryResponse,
    XReportQueryParams,
    XReportResponse,
    ZReportQueryParams,
    ZReportResponse,
)
from src.shared.infra.dependencies import get_meta
from src.shared.infra.validators import (
    RESPONSES_LIST,
    RESPONSES_QUERY,
    DataResponse,
    ListResponse,
    Meta,
)


class POSReportRouter:
    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        _read = [Depends(require_permission(Permission.REPORT_POS_READ))]

        self.router.get(
            "/x-report",
            response_model=DataResponse[XReportResponse],
            summary="X-Report (shift sales summary)",
            responses=RESPONSES_QUERY,
            dependencies=_read,
        )(self.x_report)
        self.router.get(
            "/z-report",
            response_model=DataResponse[ZReportResponse],
            summary="Z-Report (shift closing report)",
            responses=RESPONSES_QUERY,
            dependencies=_read,
        )(self.z_report)
        self.router.get(
            "/daily",
            response_model=DataResponse[DailySummaryResponse],
            summary="Daily sales summary",
            responses=RESPONSES_QUERY,
            dependencies=_read,
        )(self.daily_summary)
        self.router.get(
            "/by-payment-method",
            response_model=ListResponse[PaymentMethodSummaryResponse],
            summary="Sales by payment method",
            responses=RESPONSES_LIST,
            dependencies=_read,
        )(self.by_payment_method)

    def x_report(
        self,
        handler: Injected[GetXReportQueryHandler],
        query_params: XReportQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[XReportResponse]:
        """Generate an X-Report — a mid-shift read-only sales summary. Does not close the shift."""
        result = handler.handle(GetXReportQuery(shift_id=query_params.shift_id))
        return DataResponse(data=XReportResponse.model_validate(result), meta=meta)

    def z_report(
        self,
        handler: Injected[GetZReportQueryHandler],
        query_params: ZReportQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[ZReportResponse]:
        """Generate a Z-Report — an end-of-shift closing report with sales totals, payments, and cash balance."""
        result = handler.handle(GetZReportQuery(shift_id=query_params.shift_id))
        return DataResponse(data=ZReportResponse.model_validate(result), meta=meta)

    def daily_summary(
        self,
        handler: Injected[GetDailySummaryQueryHandler],
        query_params: DailySummaryQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[DailySummaryResponse]:
        """Get an aggregated daily sales summary including totals, sale count, and average ticket."""
        result = handler.handle(
            GetDailySummaryQuery(**query_params.model_dump(exclude_none=True))
        )
        return DataResponse(data=DailySummaryResponse.model_validate(result), meta=meta)

    def by_payment_method(
        self,
        handler: Injected[GetSalesByPaymentMethodQueryHandler],
        query_params: ByPaymentMethodQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> ListResponse[PaymentMethodSummaryResponse]:
        """Get sales totals grouped by payment method for a date range."""
        result = handler.handle(
            GetSalesByPaymentMethodQuery(
                from_date=query_params.from_date,
                to_date=query_params.to_date,
            )
        )
        return ListResponse(
            data=[PaymentMethodSummaryResponse.model_validate(r) for r in result],
            meta=meta,
        )
