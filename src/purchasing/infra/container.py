from src.purchasing.app.commands.purchase_order import (
    CancelPurchaseOrderCommandHandler,
    CreatePurchaseOrderCommandHandler,
    DeletePurchaseOrderCommandHandler,
    SendPurchaseOrderCommandHandler,
    UpdatePurchaseOrderCommandHandler,
)
from src.purchasing.app.commands.purchase_order_item import (
    AddPurchaseOrderItemCommandHandler,
    RemovePurchaseOrderItemCommandHandler,
    UpdatePurchaseOrderItemCommandHandler,
)
from src.purchasing.app.commands.purchase_receipt import (
    CreatePurchaseReceiptCommandHandler,
)
from src.purchasing.app.commands.supplier_return import (
    AddSupplierReturnItemCommandHandler,
    ConfirmSupplierReturnCommandHandler,
    CreateSupplierReturnCommandHandler,
    DeleteSupplierReturnCommandHandler,
    RemoveSupplierReturnItemCommandHandler,
    UpdateSupplierReturnCommandHandler,
    UpdateSupplierReturnItemCommandHandler,
)
from src.purchasing.app.queries.purchase_order import (
    GetAllPurchaseOrdersQueryHandler,
    GetPurchaseOrderByIdQueryHandler,
)
from src.purchasing.app.queries.purchase_order_item import (
    GetPurchaseOrderItemsByPOQueryHandler,
)
from src.purchasing.app.queries.purchase_receipt import (
    GetReceiptsByPurchaseOrderQueryHandler,
)
from src.purchasing.app.queries.supplier_return import (
    GetSupplierReturnByIdQueryHandler,
    GetSupplierReturnItemsQueryHandler,
    GetSupplierReturnsQueryHandler,
)
from src.purchasing.infra.mappers import (
    PurchaseOrderItemMapper,
    PurchaseOrderMapper,
    PurchaseReceiptItemMapper,
    PurchaseReceiptMapper,
    SupplierReturnItemMapper,
    SupplierReturnMapper,
)
from src.purchasing.infra.repositories import (
    SqlAlchemyPurchaseOrderItemRepository,
    SqlAlchemyPurchaseOrderRepository,
    SqlAlchemyPurchaseReceiptItemRepository,
    SqlAlchemyPurchaseReceiptRepository,
    SqlAlchemySupplierReturnItemRepository,
    SqlAlchemySupplierReturnRepository,
)

INJECTABLES = [
    PurchaseOrderMapper,
    PurchaseOrderItemMapper,
    PurchaseReceiptMapper,
    PurchaseReceiptItemMapper,
    SqlAlchemyPurchaseOrderRepository,
    SqlAlchemyPurchaseOrderItemRepository,
    SqlAlchemyPurchaseReceiptRepository,
    SqlAlchemyPurchaseReceiptItemRepository,
    CreatePurchaseOrderCommandHandler,
    UpdatePurchaseOrderCommandHandler,
    DeletePurchaseOrderCommandHandler,
    SendPurchaseOrderCommandHandler,
    CancelPurchaseOrderCommandHandler,
    AddPurchaseOrderItemCommandHandler,
    UpdatePurchaseOrderItemCommandHandler,
    RemovePurchaseOrderItemCommandHandler,
    CreatePurchaseReceiptCommandHandler,
    GetAllPurchaseOrdersQueryHandler,
    GetPurchaseOrderByIdQueryHandler,
    GetPurchaseOrderItemsByPOQueryHandler,
    GetReceiptsByPurchaseOrderQueryHandler,
    SupplierReturnMapper,
    SupplierReturnItemMapper,
    SqlAlchemySupplierReturnRepository,
    SqlAlchemySupplierReturnItemRepository,
    CreateSupplierReturnCommandHandler,
    UpdateSupplierReturnCommandHandler,
    DeleteSupplierReturnCommandHandler,
    AddSupplierReturnItemCommandHandler,
    UpdateSupplierReturnItemCommandHandler,
    RemoveSupplierReturnItemCommandHandler,
    ConfirmSupplierReturnCommandHandler,
    GetSupplierReturnsQueryHandler,
    GetSupplierReturnByIdQueryHandler,
    GetSupplierReturnItemsQueryHandler,
]
