from config import config


def create_wireup_container():
    from wireup import create_async_container

    from src.auth.infra.container import INJECTABLES as AUTH_INJECTABLES
    from src.catalog.product.infra.container import INJECTABLES as CATALOG_INJECTABLES
    from src.catalog.uom.infra.container import INJECTABLES as UOM_INJECTABLES
    from src.customers.infra.container import INJECTABLES as CUSTOMER_INJECTABLES
    from src.inventory.adjustment.infra.container import ADJUSTMENT_INJECTABLES
    from src.inventory.alert.infra.container import ALERT_INJECTABLES
    from src.inventory.location.infra.container import (
        INJECTABLES as LOCATION_INJECTABLES,
    )
    from src.inventory.lot.infra.container import LOT_INJECTABLES
    from src.inventory.movement.infra.container import (
        INJECTABLES as MOVEMENT_INJECTABLES,
    )
    from src.inventory.serial.infra.container import SERIAL_INJECTABLES
    from src.inventory.stock.infra.container import INJECTABLES as STOCK_INJECTABLES
    from src.inventory.transfer.infra.container import TRANSFER_INJECTABLES
    from src.inventory.warehouse.infra.container import (
        INJECTABLES as WAREHOUSE_INJECTABLES,
    )
    from src.organization.infra.container import INJECTABLES as ORGANIZATION_INJECTABLES
    from src.pos.cash.infra.container import POS_CASH_INJECTABLES
    from src.pos.refund.infra.container import POS_REFUND_INJECTABLES
    from src.pos.reports.infra.container import POS_REPORT_INJECTABLES
    from src.pos.sales.infra.container import INJECTABLES as POS_SALES_INJECTABLES
    from src.pos.shift.infra.container import INJECTABLES as POS_SHIFT_INJECTABLES
    from src.pos.terminal.infra.container import POS_TERMINAL_INJECTABLES
    from src.purchasing.infra.container import INJECTABLES as PURCHASING_INJECTABLES
    from src.reports.dashboard.infra.container import DASHBOARD_INJECTABLES
    from src.reports.inventory.infra.container import REPORT_INJECTABLES
    from src.sales.infra.container import INJECTABLES as SALES_INJECTABLES
    from src.shared.infra.database import create_session_factory
    from src.shared.infra.events.event_bus_publisher import EventBusPublisher
    from src.shared.infra.outbox.writer import OutboxWriter
    from src.shared.infra.tenant import tenant_context
    from src.suppliers.infra.container import INJECTABLES as SUPPLIER_INJECTABLES
    from src.tenancy.infra.container import INJECTABLES as TENANCY_INJECTABLES

    db_connection_string = config.DB_CONNECTION_STRING
    if not db_connection_string:
        raise ValueError("Database connection string not found in environment")

    get_db_session = create_session_factory(db_connection_string)

    container = create_async_container(
        injectables=[
            get_db_session,
            tenant_context,
            EventBusPublisher,
            OutboxWriter,
            *AUTH_INJECTABLES,
            *TENANCY_INJECTABLES,
            *ORGANIZATION_INJECTABLES,
            *CATALOG_INJECTABLES,
            *UOM_INJECTABLES,
            *WAREHOUSE_INJECTABLES,
            *LOCATION_INJECTABLES,
            *MOVEMENT_INJECTABLES,
            *STOCK_INJECTABLES,
            *LOT_INJECTABLES,
            *SERIAL_INJECTABLES,
            *ADJUSTMENT_INJECTABLES,
            *TRANSFER_INJECTABLES,
            *ALERT_INJECTABLES,
            *CUSTOMER_INJECTABLES,
            *SUPPLIER_INJECTABLES,
            *PURCHASING_INJECTABLES,
            *REPORT_INJECTABLES,
            *DASHBOARD_INJECTABLES,
            *SALES_INJECTABLES,
            *POS_TERMINAL_INJECTABLES,
            *POS_SALES_INJECTABLES,
            *POS_SHIFT_INJECTABLES,
            *POS_REFUND_INJECTABLES,
            *POS_CASH_INJECTABLES,
            *POS_REPORT_INJECTABLES,
        ]
    )

    import src.inventory.infra.event_handlers  # noqa: F401
    import src.inventory.lot.infra.event_handlers  # noqa: F401
    import src.inventory.serial.infra.event_handlers  # noqa: F401
    import src.inventory.stock.infra.event_handlers  # noqa: F401
    import src.invoicing.infra.event_handlers  # noqa: F401
    import src.purchasing.infra.event_handlers  # noqa: F401

    return container
