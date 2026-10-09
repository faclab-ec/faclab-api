"""Commands para el módulo Sales"""

from src.sales.app.commands.add_sale_item import (
    AddSaleItemCommand,
    AddSaleItemCommandHandler,
)
from src.sales.app.commands.create_sale import (
    CreateSaleCommand,
    CreateSaleCommandHandler,
)
from src.sales.app.commands.invoice_sale import (
    InvoiceSaleCommand,
    InvoiceSaleCommandHandler,
)
from src.sales.app.commands.register_payment import (
    RegisterPaymentCommand,
    RegisterPaymentCommandHandler,
)
from src.sales.app.commands.remove_sale_item import (
    RemoveSaleItemCommand,
    RemoveSaleItemCommandHandler,
)
from src.sales.app.commands.request_invoicing import (
    RequestSaleInvoicingCommand,
    RequestSaleInvoicingCommandHandler,
)

__all__ = [
    "CreateSaleCommand",
    "CreateSaleCommandHandler",
    "AddSaleItemCommand",
    "AddSaleItemCommandHandler",
    "RemoveSaleItemCommand",
    "RemoveSaleItemCommandHandler",
    "InvoiceSaleCommand",
    "InvoiceSaleCommandHandler",
    "RegisterPaymentCommand",
    "RegisterPaymentCommandHandler",
    "RequestSaleInvoicingCommand",
    "RequestSaleInvoicingCommandHandler",
]
