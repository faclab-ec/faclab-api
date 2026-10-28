from src.sales.app.commands.add_sale_item import AddSaleItemCommandHandler
from src.sales.app.commands.create_sale import CreateSaleCommandHandler
from src.sales.app.commands.invoice_sale import InvoiceSaleCommandHandler
from src.sales.app.commands.register_payment import RegisterPaymentCommandHandler
from src.sales.app.commands.reject_invoice import RejectSaleInvoiceCommandHandler
from src.sales.app.commands.remove_sale_item import RemoveSaleItemCommandHandler
from src.sales.app.commands.request_invoicing import RequestSaleInvoicingCommandHandler
from src.sales.app.commands.update_sale_item import UpdateSaleItemCommandHandler
from src.sales.app.queries.get_payments import GetSalePaymentsQueryHandler
from src.sales.app.queries.get_sale_items import GetSaleItemsQueryHandler
from src.sales.app.queries.get_sales import (
    GetAllSalesQueryHandler,
    GetSaleByIdQueryHandler,
)
from src.sales.infra.mappers import PaymentMapper, SaleItemMapper, SaleMapper
from src.sales.infra.repositories import (
    SqlAlchemyPaymentRepository,
    SqlAlchemySaleItemRepository,
    SqlAlchemySaleRepository,
)

INJECTABLES = [
    SaleMapper,
    SaleItemMapper,
    PaymentMapper,
    SqlAlchemySaleRepository,
    SqlAlchemySaleItemRepository,
    SqlAlchemyPaymentRepository,
    CreateSaleCommandHandler,
    AddSaleItemCommandHandler,
    RemoveSaleItemCommandHandler,
    UpdateSaleItemCommandHandler,
    RegisterPaymentCommandHandler,
    InvoiceSaleCommandHandler,
    RejectSaleInvoiceCommandHandler,
    RequestSaleInvoicingCommandHandler,
    GetAllSalesQueryHandler,
    GetSaleByIdQueryHandler,
    GetSaleItemsQueryHandler,
    GetSalePaymentsQueryHandler,
]
