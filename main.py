import copy
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from wireup.integration.fastapi import setup as wireup_fastapi_setup

import src
from config import config
from src.auth.infra.admin_routes import UserAdminRouter
from src.auth.infra.middleware import AuthMiddleware
from src.auth.infra.routes import AuthRouter
from src.auth.infra.token_service import JwtTokenService
from src.catalog.product.infra.routes import CategoryRouter, ProductRouter
from src.catalog.uom.infra.routes import UnitOfMeasureRouter
from src.container import create_wireup_container
from src.customers.infra.routes import CustomerContactRouter, CustomerRouter
from src.inventory.adjustment.infra.routes import AdjustmentItemRouter, AdjustmentRouter
from src.inventory.alert.infra.routes import AlertRouter
from src.inventory.location.infra.routes import LocationRouter
from src.inventory.lot.infra.routes import LotRouter
from src.inventory.movement.infra.routes import MovementRouter
from src.inventory.serial.infra.routes import SerialRouter
from src.inventory.stock.infra.routes import StockRouter
from src.inventory.transfer.infra.routes import TransferItemRouter, TransferRouter
from src.inventory.warehouse.infra.routes import WarehouseRouter
from src.pos.cash.infra.routes import POSCashRouter
from src.pos.infra.routes import POSCustomerRouter, POSProductRouter
from src.pos.refund.infra.routes import POSRefundRouter
from src.pos.reports.infra.routes import POSReportRouter
from src.pos.sales.infra.routes import POSSaleRouter
from src.pos.shift.infra.routes import POSShiftRouter
from src.purchasing.infra.routes import POItemRouter, PurchaseOrderRouter
from src.reports.inventory.infra.routes import ReportRouter
from src.sales.infra.routes import SaleRouter
from src.shared.infra.adapters import OpenTelemetry
from src.shared.infra.logging import configure_logging
from src.shared.infra.middlewares import ErrorHandlingMiddleware
from src.suppliers.infra.routes import (
    SupplierContactRouter,
    SupplierProductRouter,
    SupplierRouter,
)

configure_logging(
    log_level=config.LOG_LEVEL,
    json_output=config.ENVIRONMENT != "local",
)

logger = structlog.get_logger(__name__)

origins = ["http://localhost:3000", "http://localhost:5173"]

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

_docs = config.get_docs_config()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    yield

    from src.shared.infra.kafka.event_handlers import _get_producer

    producer = _get_producer()
    if producer:
        producer.close()

    otel.shutdown()


app = FastAPI(
    title=_docs.title,
    version=_docs.version,
    description=_docs.description,
    openapi_tags=_docs.openapi_tags,
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)


def _custom_openapi() -> dict:
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=_docs.openapi_tags,
    )
    schema["x-tagGroups"] = _docs.tag_groups
    schema.setdefault("components", {})["securitySchemes"] = {
        "bearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
    }
    schema["security"] = [{"bearerAuth": []}]
    for public_path in ("/api/auth/login", "/api/auth/refresh"):
        path_item = schema.get("paths", {}).get(public_path, {})
        for operation in path_item.values():
            if isinstance(operation, dict):
                operation["security"] = []
    app.openapi_schema = schema
    return schema


app.openapi = _custom_openapi  # ty: ignore[invalid-assignment]

# ---------------------------------------------------------------------------
# Scalar docs helpers
# ---------------------------------------------------------------------------

_SCALAR_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
  <title>{title}</title>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🏷️</text></svg>" />
  <style>body {{ margin: 0; }}</style>
</head>
<body>
  <script
    id="api-reference"
    data-url="{schema_url}"
    data-configuration='{config}'
  ></script>
  <script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference"></script>
</body>
</html>"""


def _scalar_response(title: str, schema_url: str) -> HTMLResponse:
    cfg = json.dumps(
        {
            "layout": "sidebar",
            "theme": "default",
            "searchHotKey": "k",
            "defaultHttpClient": {
                "targetKey": "python",
                "clientKey": "requests",
            },
            "withDefaultFonts": True,
            "hideDownloadButton": False,
            "hideDarkModeToggle": False,
        }
    )
    return HTMLResponse(
        _SCALAR_TEMPLATE.format(title=title, schema_url=schema_url, config=cfg)
    )


def _filtered_schema(path_prefixes: tuple[str, ...]) -> dict:
    """Return a deepcopy of the full schema containing only operations whose paths start with one of *path_prefixes*."""
    schema = copy.deepcopy(app.openapi())
    used_tags: set[str] = set()
    filtered_paths: dict = {}

    for path, path_item in schema.get("paths", {}).items():
        if not any(path.startswith(p) for p in path_prefixes):
            continue
        filtered_paths[path] = path_item
        for _method, operation in path_item.items():
            if isinstance(operation, dict):
                used_tags.update(operation.get("tags", []))

    schema["paths"] = filtered_paths
    schema["tags"] = [t for t in schema.get("tags", []) if t["name"] in used_tags]
    schema["x-tagGroups"] = [
        g
        for g in schema.get("x-tagGroups", [])
        if any(t in used_tags for t in g["tags"])
    ]
    return schema


# ---------------------------------------------------------------------------
# OTEL + DI
# ---------------------------------------------------------------------------

otel = OpenTelemetry()
otel.instrument(app, config.get_otel_config())

wireup_container = create_wireup_container()
src.wireup_container = wireup_container

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

# Admin API
admin_router = APIRouter(prefix="/api/admin")
admin_router.include_router(
    CategoryRouter().router, prefix="/categories", tags=["Categories"]
)
admin_router.include_router(
    UnitOfMeasureRouter().router,
    prefix="/units-of-measure",
    tags=["Units of Measure"],
)
admin_router.include_router(
    ProductRouter().router, prefix="/products", tags=["Products"]
)
admin_router.include_router(
    WarehouseRouter().router, prefix="/warehouses", tags=["Warehouses"]
)
admin_router.include_router(
    LocationRouter().router, prefix="/locations", tags=["Locations"]
)
admin_router.include_router(StockRouter().router, prefix="/stock", tags=["Stock"])
admin_router.include_router(
    MovementRouter().router, prefix="/movements", tags=["Movements"]
)
admin_router.include_router(LotRouter().router, prefix="/lots", tags=["Lots"])
admin_router.include_router(SerialRouter().router, prefix="/serials", tags=["Serials"])
admin_router.include_router(
    CustomerRouter().router, prefix="/customers", tags=["Customers"]
)
admin_router.include_router(
    CustomerContactRouter().router,
    prefix="/customer-contacts",
    tags=["Customer Contacts"],
)
admin_router.include_router(
    SupplierRouter().router, prefix="/suppliers", tags=["Suppliers"]
)
admin_router.include_router(
    SupplierContactRouter().router,
    prefix="/supplier-contacts",
    tags=["Supplier Contacts"],
)
admin_router.include_router(
    SupplierProductRouter().router,
    prefix="/supplier-products",
    tags=["Supplier Products"],
)
admin_router.include_router(
    PurchaseOrderRouter().router,
    prefix="/purchase-orders",
    tags=["Purchase Orders"],
)
admin_router.include_router(
    POItemRouter().router,
    prefix="/purchase-order-items",
    tags=["Purchase Order Items"],
)
admin_router.include_router(SaleRouter().router, prefix="/sales", tags=["Sales"])
admin_router.include_router(
    AdjustmentRouter().router,
    prefix="/adjustments",
    tags=["Adjustments"],
)
admin_router.include_router(
    AdjustmentItemRouter().router,
    prefix="/adjustment-items",
    tags=["Adjustment Items"],
)
admin_router.include_router(
    TransferRouter().router,
    prefix="/transfers",
    tags=["Transfers"],
)
admin_router.include_router(
    TransferItemRouter().router,
    prefix="/transfer-items",
    tags=["Transfer Items"],
)
admin_router.include_router(AlertRouter().router, prefix="/alerts", tags=["Alerts"])
admin_router.include_router(UserAdminRouter().router, prefix="/users", tags=["Users"])
admin_router.include_router(
    ReportRouter().router,
    prefix="/reports/inventory",
    tags=["Inventory Reports"],
)

# POS API
pos_router = APIRouter(prefix="/api/pos")
pos_router.include_router(POSSaleRouter().router, prefix="/sales", tags=["POS Sales"])
pos_router.include_router(POSShiftRouter().router, prefix="/shifts", tags=["Shifts"])
pos_router.include_router(
    POSProductRouter().router, prefix="/products", tags=["Product Search"]
)
pos_router.include_router(
    POSCustomerRouter().router, prefix="/customers", tags=["Customer Search"]
)
pos_router.include_router(POSRefundRouter().router, prefix="/refunds", tags=["Refunds"])
pos_router.include_router(
    POSCashRouter().router, prefix="/shifts", tags=["Cash Drawer"]
)
pos_router.include_router(
    POSReportRouter().router, prefix="/reports", tags=["POS Reports"]
)

# Auth API
auth_router = APIRouter(prefix="/api/auth")
auth_router.include_router(AuthRouter().router, tags=["Auth"])

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

app.add_middleware(AuthMiddleware, token_service=JwtTokenService())
app.add_middleware(ErrorHandlingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin_router)
app.include_router(pos_router)
app.include_router(auth_router)

# ---------------------------------------------------------------------------
# Doc endpoints (only registered when DOCS_ENABLED=true)
# ---------------------------------------------------------------------------

if _docs.enabled:

    @app.get("/docs", include_in_schema=False)
    async def scalar_docs():
        """Interactive API reference — all endpoints."""
        return _scalar_response(f"{_docs.title} — Reference", "/openapi.json")

    @app.get("/docs/admin", include_in_schema=False)
    async def scalar_admin_docs():
        """Interactive API reference — Admin endpoints only."""
        return _scalar_response(f"{_docs.title} — Admin", "/openapi/admin.json")

    @app.get("/docs/pos", include_in_schema=False)
    async def scalar_pos_docs():
        """Interactive API reference — POS endpoints only."""
        return _scalar_response(f"{_docs.title} — POS", "/openapi/pos.json")

    @app.get("/openapi/admin.json", include_in_schema=False)
    async def admin_openapi_schema():
        return JSONResponse(_filtered_schema(("/api/admin", "/api/auth")))

    @app.get("/openapi/pos.json", include_in_schema=False)
    async def pos_openapi_schema():
        return JSONResponse(_filtered_schema(("/api/pos", "/api/auth")))


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse("/docs")


wireup_fastapi_setup(wireup_container, app)


if __name__ == "__main__":
    import uvicorn

    logger.info("starting_api")
    uvicorn.run(app, host="0.0.0.0", port=3000)
