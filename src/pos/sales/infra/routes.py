"""POS sale routes"""

from fastapi import APIRouter, Depends, status
from wireup import Injected

from src.auth.domain.permissions import Permission
from src.auth.infra.dependencies import require_permission
from src.pos.sales.app.commands.apply_discount import (
    ApplySaleDiscountCommand,
    ApplySaleDiscountCommandHandler,
)
from src.pos.sales.app.commands.cancel_sale import (
    POSCancelSaleCommand,
    POSCancelSaleCommandHandler,
)
from src.pos.sales.app.commands.confirm_sale import (
    POSConfirmSaleCommand,
    POSConfirmSaleCommandHandler,
)
from src.pos.sales.app.commands.create_sale import (
    POSCreateSaleCommand,
    POSCreateSaleCommandHandler,
)
from src.pos.sales.app.commands.override_price import (
    OverrideItemPriceCommand,
    OverrideItemPriceCommandHandler,
)
from src.pos.sales.app.commands.park_sale import (
    ParkSaleCommand,
    POSParkSaleCommandHandler,
)
from src.pos.sales.app.commands.quick_sale import (
    QuickSaleCommand,
    QuickSaleCommandHandler,
)
from src.pos.sales.app.commands.resume_sale import (
    POSResumeSaleCommandHandler,
    ResumeSaleCommand,
)
from src.pos.sales.app.queries.generate_receipt import (
    GenerateReceiptQuery,
    GenerateReceiptQueryHandler,
)
from src.pos.sales.app.queries.get_parked_sales import (
    GetParkedSalesQuery,
    GetParkedSalesQueryHandler,
)
from src.pos.sales.infra.validators import (
    ApplyDiscountRequest,
    OverridePriceRequest,
    ParkSaleRequest,
    POSSaleRequest,
    QuickSaleRequest,
    ReceiptResponse,
)
from src.sales.app.commands.add_sale_item import (
    AddSaleItemCommand,
    AddSaleItemCommandHandler,
)
from src.sales.app.commands.register_payment import (
    RegisterPaymentCommand,
    RegisterPaymentCommandHandler,
)
from src.sales.app.commands.remove_sale_item import (
    RemoveSaleItemCommand,
    RemoveSaleItemCommandHandler,
)
from src.sales.app.commands.update_sale_item import (
    UpdateSaleItemCommand,
    UpdateSaleItemCommandHandler,
)
from src.sales.app.queries.get_payments import (
    GetSalePaymentsQuery,
    GetSalePaymentsQueryHandler,
)
from src.sales.app.queries.get_sale_items import (
    GetSaleItemsQuery,
    GetSaleItemsQueryHandler,
)
from src.sales.app.queries.get_sales import GetSaleByIdQuery, GetSaleByIdQueryHandler
from src.sales.infra.validators import (
    CancelSaleRequest,
    PaymentRequest,
    PaymentResponse,
    SaleDetailResponse,
    SaleItemRequest,
    SaleItemResponse,
    SaleItemUpdateRequest,
    SaleResponse,
)
from src.shared.infra.dependencies import get_meta
from src.shared.infra.validators import (
    RESPONSES_COMMAND,
    RESPONSES_DELETE,
    RESPONSES_LIST,
    RESPONSES_QUERY,
    DataResponse,
    ListResponse,
    Meta,
)


class POSSaleRouter:
    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        _pos = [Depends(require_permission(Permission.POS_OPERATE))]

        self.router.post(
            "",
            response_model=DataResponse[SaleResponse],
            status_code=status.HTTP_201_CREATED,
            summary="Create sale",
            responses=RESPONSES_COMMAND,
            dependencies=_pos,
        )(self.create_sale)
        self.router.post(
            "/quick",
            response_model=DataResponse[SaleDetailResponse],
            status_code=status.HTTP_201_CREATED,
            summary="Quick sale (checkout in one request)",
            responses=RESPONSES_COMMAND,
            dependencies=_pos,
        )(self.quick_sale)
        self.router.get(
            "/parked",
            response_model=ListResponse[SaleResponse],
            summary="List parked sales",
            responses=RESPONSES_LIST,
            dependencies=_pos,
        )(self.get_parked_sales)
        self.router.get(
            "/{sale_id}",
            response_model=DataResponse[SaleResponse],
            summary="Get sale",
            responses=RESPONSES_QUERY,
            dependencies=_pos,
        )(self.get_sale)
        self.router.post(
            "/{sale_id}/items",
            response_model=DataResponse[SaleItemResponse],
            status_code=status.HTTP_201_CREATED,
            summary="Add item to sale",
            responses=RESPONSES_COMMAND,
            dependencies=_pos,
        )(self.add_sale_item)
        self.router.get(
            "/{sale_id}/items",
            response_model=ListResponse[SaleItemResponse],
            summary="List sale items",
            responses=RESPONSES_LIST,
            dependencies=_pos,
        )(self.get_sale_items)
        self.router.put(
            "/{sale_id}/items/{item_id}",
            response_model=DataResponse[SaleItemResponse],
            summary="Update sale item",
            responses=RESPONSES_COMMAND,
            dependencies=_pos,
        )(self.update_sale_item)
        self.router.delete(
            "/{sale_id}/items/{item_id}",
            summary="Remove item from sale",
            responses=RESPONSES_DELETE,
            dependencies=_pos,
        )(self.remove_sale_item)
        self.router.post(
            "/{sale_id}/confirm",
            response_model=DataResponse[SaleResponse],
            summary="Confirm sale",
            responses=RESPONSES_COMMAND,
            dependencies=_pos,
        )(self.confirm_sale)
        self.router.post(
            "/{sale_id}/cancel",
            response_model=DataResponse[SaleResponse],
            summary="Cancel sale",
            responses=RESPONSES_COMMAND,
            dependencies=_pos,
        )(self.cancel_sale)
        self.router.post(
            "/{sale_id}/park",
            response_model=DataResponse[SaleResponse],
            summary="Park sale",
            responses=RESPONSES_COMMAND,
            dependencies=_pos,
        )(self.park_sale)
        self.router.post(
            "/{sale_id}/resume",
            response_model=DataResponse[SaleResponse],
            summary="Resume parked sale",
            responses=RESPONSES_COMMAND,
            dependencies=_pos,
        )(self.resume_sale)
        self.router.post(
            "/{sale_id}/discount",
            response_model=DataResponse[SaleResponse],
            summary="Apply discount to sale",
            responses=RESPONSES_COMMAND,
            dependencies=_pos,
        )(self.apply_discount)
        self.router.post(
            "/{sale_id}/payments",
            response_model=DataResponse[PaymentResponse],
            status_code=status.HTTP_201_CREATED,
            summary="Register payment",
            responses=RESPONSES_COMMAND,
            dependencies=_pos,
        )(self.register_payment)
        self.router.get(
            "/{sale_id}/payments",
            response_model=ListResponse[PaymentResponse],
            summary="List sale payments",
            responses=RESPONSES_LIST,
            dependencies=_pos,
        )(self.get_sale_payments)
        self.router.put(
            "/{sale_id}/items/{item_id}/price",
            response_model=DataResponse[SaleItemResponse],
            summary="Override item price",
            responses=RESPONSES_COMMAND,
            dependencies=_pos,
        )(self.override_item_price)
        self.router.get(
            "/{sale_id}/receipt",
            response_model=DataResponse[ReceiptResponse],
            summary="Generate receipt",
            responses=RESPONSES_QUERY,
            dependencies=_pos,
        )(self.generate_receipt)

    def create_sale(
        self,
        handler: Injected[POSCreateSaleCommandHandler],
        sale: POSSaleRequest,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[SaleResponse]:
        """Create a new POS sale in DRAFT status.

        The sale must have items added and payments registered before it can be confirmed.
        Optionally associate a customer or mark it as a final-consumer sale.
        """
        result = handler.handle(
            POSCreateSaleCommand(**sale.model_dump(exclude_none=True))
        )
        return DataResponse(data=SaleResponse.model_validate(result), meta=meta)

    def quick_sale(
        self,
        handler: Injected[QuickSaleCommandHandler],
        sale: QuickSaleRequest,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[SaleDetailResponse]:
        """Complete a sale in a single request — creates the sale, adds items, registers payments, and confirms.

        This is the fastest checkout flow: supply line items and payments, and the sale
        is created and confirmed atomically. Inventory movements are generated immediately.
        An optional sale-level discount (`discountType`/`discountValue`) follows the same
        rules as `POST /sales/{sale_id}/discount`; VAT is computed after the discount.
        """
        result = handler.handle(
            QuickSaleCommand(
                items=[item.model_dump() for item in sale.items],
                payments=[p.model_dump() for p in sale.payments],
                customer_id=sale.customer_id,
                discount_type=sale.discount_type,
                discount_value=sale.discount_value,
                notes=sale.notes,
                created_by=sale.created_by,
            )
        )
        return DataResponse(data=SaleDetailResponse.model_validate(result), meta=meta)

    def get_sale(
        self,
        handler: Injected[GetSaleByIdQueryHandler],
        sale_id: int,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[SaleResponse]:
        """Retrieve a sale by its ID, including current status and totals."""
        result = handler.handle(GetSaleByIdQuery(sale_id=sale_id))
        return DataResponse(data=SaleResponse.model_validate(result), meta=meta)

    def add_sale_item(
        self,
        handler: Injected[AddSaleItemCommandHandler],
        sale_id: int,
        item: SaleItemRequest,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[SaleItemResponse]:
        """Add a line item to a DRAFT sale. The sale totals are recalculated automatically."""
        result = handler.handle(
            AddSaleItemCommand(sale_id=sale_id, **item.model_dump(exclude_none=True))
        )
        return DataResponse(data=SaleItemResponse.model_validate(result), meta=meta)

    def get_sale_items(
        self,
        handler: Injected[GetSaleItemsQueryHandler],
        sale_id: int,
        meta: Meta = Depends(get_meta),
    ) -> ListResponse[SaleItemResponse]:
        """List all line items for a sale."""
        result = handler.handle(GetSaleItemsQuery(sale_id=sale_id))
        return ListResponse(
            data=[SaleItemResponse.model_validate(r) for r in result], meta=meta
        )

    def update_sale_item(
        self,
        handler: Injected[UpdateSaleItemCommandHandler],
        sale_id: int,
        item_id: int,
        item: SaleItemUpdateRequest,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[SaleItemResponse]:
        """Update quantity or discount of a line item in a DRAFT sale."""
        result = handler.handle(
            UpdateSaleItemCommand(
                sale_id=sale_id,
                sale_item_id=item_id,
                **item.model_dump(exclude_none=True),
            )
        )
        return DataResponse(data=SaleItemResponse.model_validate(result), meta=meta)

    def remove_sale_item(
        self,
        handler: Injected[RemoveSaleItemCommandHandler],
        sale_id: int,
        item_id: int,
    ) -> dict:
        """Remove a line item from a DRAFT sale."""
        return handler.handle(
            RemoveSaleItemCommand(sale_id=sale_id, sale_item_id=item_id)
        )

    def confirm_sale(
        self,
        handler: Injected[POSConfirmSaleCommandHandler],
        sale_id: int,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[SaleResponse]:
        """Confirm a sale and trigger inventory movements.

        The sale must have at least one item and payments covering the total amount.
        Once confirmed, inventory OUT movements are created for each line item.
        """
        result = handler.handle(POSConfirmSaleCommand(sale_id=sale_id))
        return DataResponse(data=SaleResponse.model_validate(result), meta=meta)

    def cancel_sale(
        self,
        handler: Injected[POSCancelSaleCommandHandler],
        sale_id: int,
        cancel_input: CancelSaleRequest | None = None,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[SaleResponse]:
        """Cancel a sale. If the sale was confirmed, inventory movements are reversed."""
        reason = cancel_input.reason if cancel_input else None
        result = handler.handle(POSCancelSaleCommand(sale_id=sale_id, reason=reason))
        return DataResponse(data=SaleResponse.model_validate(result), meta=meta)

    def apply_discount(
        self,
        handler: Injected[ApplySaleDiscountCommandHandler],
        sale_id: int,
        discount_input: ApplyDiscountRequest,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[SaleResponse]:
        """Apply a percentage or fixed-amount discount to a DRAFT sale.

        The discount is applied to the sale subtotal before tax calculation.
        """
        result = handler.handle(
            ApplySaleDiscountCommand(sale_id=sale_id, **discount_input.model_dump())
        )
        return DataResponse(data=SaleResponse.model_validate(result), meta=meta)

    def register_payment(
        self,
        handler: Injected[RegisterPaymentCommandHandler],
        sale_id: int,
        payment: PaymentRequest,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[PaymentResponse]:
        """Register a payment against a sale. Multiple payments with different methods are supported."""
        result = handler.handle(
            RegisterPaymentCommand(
                sale_id=sale_id, **payment.model_dump(exclude_none=True)
            )
        )
        return DataResponse(data=PaymentResponse.model_validate(result), meta=meta)

    def get_sale_payments(
        self,
        handler: Injected[GetSalePaymentsQueryHandler],
        sale_id: int,
        meta: Meta = Depends(get_meta),
    ) -> ListResponse[PaymentResponse]:
        """List all payments registered for a sale."""
        result = handler.handle(GetSalePaymentsQuery(sale_id=sale_id))
        return ListResponse(
            data=[PaymentResponse.model_validate(r) for r in result], meta=meta
        )

    def park_sale(
        self,
        handler: Injected[POSParkSaleCommandHandler],
        sale_id: int,
        park_input: ParkSaleRequest | None = None,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[SaleResponse]:
        """Park (hold) a DRAFT sale for later. Parked sales appear in the parked-sales list."""
        reason = park_input.reason if park_input else None
        result = handler.handle(ParkSaleCommand(sale_id=sale_id, reason=reason))
        return DataResponse(data=SaleResponse.model_validate(result), meta=meta)

    def resume_sale(
        self,
        handler: Injected[POSResumeSaleCommandHandler],
        sale_id: int,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[SaleResponse]:
        """Resume a previously parked sale, returning it to DRAFT status."""
        result = handler.handle(ResumeSaleCommand(sale_id=sale_id))
        return DataResponse(data=SaleResponse.model_validate(result), meta=meta)

    def get_parked_sales(
        self,
        handler: Injected[GetParkedSalesQueryHandler],
        meta: Meta = Depends(get_meta),
    ) -> ListResponse[SaleResponse]:
        """List all currently parked sales awaiting resumption."""
        result = handler.handle(GetParkedSalesQuery())
        return ListResponse(
            data=[SaleResponse.model_validate(r) for r in result], meta=meta
        )

    def override_item_price(
        self,
        handler: Injected[OverrideItemPriceCommandHandler],
        sale_id: int,
        item_id: int,
        body: OverridePriceRequest,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[SaleItemResponse]:
        """Override the unit price of a sale item. A reason is required for audit purposes."""
        result = handler.handle(
            OverrideItemPriceCommand(
                sale_id=sale_id,
                item_id=item_id,
                new_price=body.new_price,
                reason=body.reason,
            )
        )
        return DataResponse(data=SaleItemResponse.model_validate(result), meta=meta)

    def generate_receipt(
        self,
        handler: Injected[GenerateReceiptQueryHandler],
        sale_id: int,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[ReceiptResponse]:
        """Generate a printable receipt for a confirmed sale, including items, tax breakdown, and payments."""
        result = handler.handle(GenerateReceiptQuery(sale_id=sale_id))
        return DataResponse(data=ReceiptResponse.model_validate(result), meta=meta)
