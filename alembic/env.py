from logging.config import fileConfig

from environs import Env
from sqlalchemy import engine_from_config, pool

from alembic import context

# Import all models for autogenerate support
from src.auth.infra.models import UserModel  # noqa: F401
from src.catalog.product.infra.models import CategoryModel, ProductModel  # noqa: F401
from src.catalog.uom.infra.models import UnitOfMeasureModel  # noqa: F401
from src.customers.infra.models import CustomerContactModel, CustomerModel  # noqa: F401
from src.inventory.adjustment.infra.models import (  # noqa: F401
    AdjustmentItemModel,
    InventoryAdjustmentModel,
)
from src.inventory.location.infra.models import LocationModel  # noqa: F401
from src.inventory.lot.infra.models import LotModel, MovementLotItemModel  # noqa: F401
from src.inventory.movement.infra.models import MovementModel  # noqa: F401
from src.inventory.serial.infra.models import SerialNumberModel  # noqa: F401
from src.inventory.stock.infra.models import StockModel  # noqa: F401
from src.inventory.transfer.infra.models import (  # noqa: F401
    StockTransferItemModel,
    StockTransferModel,
)
from src.inventory.warehouse.infra.models import WarehouseModel  # noqa: F401
from src.organization.infra.models import (  # noqa: F401
    BranchModel,
    EmissionPointModel,
    PosTerminalModel,
)
from src.pos.cash.infra.models import CashMovementModel  # noqa: F401
from src.pos.refund.infra.models import (  # noqa: F401
    RefundItemModel,
    RefundModel,
    RefundPaymentModel,
)
from src.pos.shift.infra.models import ShiftModel  # noqa: F401
from src.purchasing.infra.models import (  # noqa: F401
    PurchaseOrderItemModel,
    PurchaseOrderModel,
    PurchaseReceiptItemModel,
    PurchaseReceiptModel,
)
from src.sales.infra.models import PaymentModel, SaleItemModel, SaleModel  # noqa: F401
from src.shared.infra.database import Base
from src.shared.infra.outbox.models import OutboxMessageModel  # noqa: F401
from src.suppliers.infra.models import (  # noqa: F401
    SupplierContactModel,
    SupplierModel,
    SupplierProductModel,
)
from src.tenancy.infra.models import (  # noqa: F401
    MembershipModel,
    TenantModel,
    UserBranchAccessModel,
)

env = Env()
env.read_env()

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config


# Migrations run as faclab_owner, the owner of the tables (S2.4); without its own
# URL they use the API's (local SQLite)
db_url = env("DATABASE_URL_MIGRATIONS", "") or env(
    "DATABASE_URL", "sqlite:///./default.db"
)
# The ini parser interpolates "%": a password may contain it
config.set_main_option("sqlalchemy.url", db_url.replace("%", "%%"))

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
