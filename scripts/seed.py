"""Datos de ejemplo para desarrollo local. Reemplaza los datos de negocio de sus
dos empresas.

Crea (o reutiliza) dos empresas con el administrador de `AUTH_SEED_*`: la de
`make seed-admin` y una segunda de ejemplo. Las dos reciben el mismo catálogo,
con los mismos SKU, identificaciones, códigos de bodega y números de orden de
compra, para probar que cada empresa ve solo lo suyo. Al iniciar sesión, el
administrador elige la empresa. Cada empresa tiene tres sucursales (Quito, la
matriz, Guayaquil y Cuenca), cada una con su punto de emisión, su bodega y una
terminal.

Usage:
    AUTH_SEED_USERNAME=admin AUTH_SEED_EMAIL=admin@faclab.local \\
    AUTH_SEED_PASSWORD=... python -m scripts.seed
"""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from environs import Env
from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from src.auth.seed import LOCAL_TENANT_NAME, LOCAL_TENANT_RUC
from src.catalog.product.infra.models import CategoryModel, ProductModel
from src.catalog.uom.infra.models import UnitOfMeasureModel
from src.customers.infra.models import CustomerContactModel, CustomerModel
from src.inventory.adjustment.infra.models import (
    AdjustmentItemModel,
    InventoryAdjustmentModel,
)
from src.inventory.location.domain.entities import LocationType
from src.inventory.location.infra.models import LocationModel
from src.inventory.lot.infra.models import LotModel, MovementLotItemModel
from src.inventory.movement.domain.constants import MovementType
from src.inventory.movement.infra.models import MovementModel
from src.inventory.serial.infra.models import SerialNumberModel
from src.inventory.stock.infra.models import StockModel
from src.inventory.transfer.infra.models import (
    StockTransferItemModel,
    StockTransferModel,
)
from src.inventory.warehouse.infra.models import WarehouseModel
from src.organization.infra.models import (
    BranchModel,
    EmissionPointModel,
    PosTerminalModel,
)
from src.pos.shift.infra.models import ShiftModel  # noqa: F401  # sales.shift_id FK
from src.purchasing.infra.models import (
    PurchaseOrderItemModel,
    PurchaseOrderModel,
    PurchaseReceiptItemModel,
    PurchaseReceiptModel,
)
from src.sales.infra.models import PaymentModel, SaleItemModel, SaleModel
from src.shared.domain.tenant import TenantContext, TenantSource
from src.shared.infra.database import create_session_maker
from src.shared.infra.tenant import tenant_scope
from src.suppliers.infra.models import (
    SupplierContactModel,
    SupplierModel,
    SupplierProductModel,
)
from src.tenancy.app.commands.provision_tenant import ProvisionTenantCommand
from src.tenancy.infra.models import UserBranchAccessModel
from src.tenancy.provision import provision

# Made up, with a valid check digit: no real company
SECOND_TENANT_RUC = "0999999999001"
SECOND_TENANT_NAME = "Ferretería Demo Dos"

TRUNCATE_ORDER = [
    UserBranchAccessModel,
    PosTerminalModel,
    StockTransferItemModel,
    StockTransferModel,
    AdjustmentItemModel,
    InventoryAdjustmentModel,
    PaymentModel,
    SaleItemModel,
    SaleModel,
    PurchaseReceiptItemModel,
    PurchaseReceiptModel,
    PurchaseOrderItemModel,
    PurchaseOrderModel,
    SerialNumberModel,
    MovementLotItemModel,
    MovementModel,
    LotModel,
    StockModel,
    SupplierProductModel,
    SupplierContactModel,
    SupplierModel,
    CustomerContactModel,
    CustomerModel,
    LocationModel,
    ProductModel,
    CategoryModel,
    UnitOfMeasureModel,
    WarehouseModel,
    EmissionPointModel,
    BranchModel,
]


def ensure_local_environment() -> None:
    """The seed empties the business tables, so it only runs in local."""
    env = Env()
    env.read_env()
    environment = env("ENVIRONMENT", "local")
    if environment != "local":
        raise SystemExit(
            f"El seed borra los datos y solo corre con ENVIRONMENT=local "
            f"(actual: {environment})"
        )


def get_session_maker() -> sessionmaker[Session]:
    """The app's session maker: new rows get the tenant of the context"""
    env = Env()
    env.read_env()
    return create_session_maker(env("DATABASE_URL", "sqlite:///./default.db"))


def provision_tenants() -> list[UUID]:
    """The seed admin's tenant and a second one, both with that admin.
    Idempotent: existing tenants, user and memberships are reused."""
    env = Env()
    env.read_env()
    tenants = [
        (
            env("AUTH_SEED_TENANT_RUC", LOCAL_TENANT_RUC),
            env("AUTH_SEED_TENANT_NAME", LOCAL_TENANT_NAME),
        ),
        (SECOND_TENANT_RUC, SECOND_TENANT_NAME),
    ]
    return [
        provision(
            ProvisionTenantCommand(
                ruc=ruc,
                legal_name=legal_name,
                admin_username=env("AUTH_SEED_USERNAME"),
                admin_email=env("AUTH_SEED_EMAIL"),
                admin_password=env("AUTH_SEED_PASSWORD", None),
            )
        )["tenant_id"]
        for ruc, legal_name in tenants
    ]


def truncate_tenant(session: Session, tenant_id: UUID):
    """Deletes the tenant's business rows. Runs in its context: row-level
    security keeps any other tenant out of reach anyway (S2.4)"""
    for model in TRUNCATE_ORDER:
        session.execute(delete(model).where(model.tenant_id == tenant_id))
    session.flush()


def seed_categories(session: Session) -> list[CategoryModel]:
    data = [
        ("Electrónica", "Dispositivos y componentes electrónicos"),
        ("Ferretería", "Herramientas y materiales de construcción"),
        ("Oficina", "Suministros de oficina"),
        ("Limpieza", "Productos de limpieza industrial"),
        ("Seguridad Industrial", "Equipos de protección personal"),
        ("Iluminación", "Lámparas y accesorios de iluminación"),
        ("Plomería", "Tubería y accesorios de plomería"),
    ]
    models = [CategoryModel(name=name, description=desc) for name, desc in data]
    session.add_all(models)
    session.flush()
    return models


def seed_uoms(session: Session) -> list[UnitOfMeasureModel]:
    data = [
        ("Unidad", "und", "Unidad individual"),
        ("Kilogramo", "kg", "Peso en kilogramos"),
        ("Litro", "lt", "Volumen en litros"),
        ("Metro", "m", "Longitud en metros"),
        ("Caja", "caja", "Caja de productos"),
        ("Par", "par", "Par de unidades"),
        ("Rollo", "rollo", "Rollo de material"),
        ("Galón", "gal", "Volumen en galones"),
        ("Paquete", "paq", "Paquete de productos"),
    ]
    models = [
        UnitOfMeasureModel(name=name, symbol=symbol, description=desc)
        for name, symbol, desc in data
    ]
    session.add_all(models)
    session.flush()
    return models


def seed_branches(session: Session) -> list[BranchModel]:
    """Quito is the main branch (matriz); each one has emission point 001"""
    data = [
        ("001", "Matriz Quito", "Av. 10 de Agosto N37-45, Quito", True),
        ("002", "Sucursal Guayaquil", "Km 6.5 Vía Daule, Guayaquil", False),
        ("003", "Sucursal Cuenca", "Av. de las Américas 3-42, Cuenca", False),
    ]
    branches = [
        BranchModel(establishment_code=code, name=name, address=address, is_main=main)
        for code, name, address, main in data
    ]
    session.add_all(branches)
    session.flush()
    session.add_all(
        EmissionPointModel(branch_id=branch.id, code="001", name="Caja principal")
        for branch in branches
    )
    session.flush()
    return branches


def seed_warehouses(
    session: Session, branches: list[BranchModel]
) -> list[WarehouseModel]:
    """One warehouse per branch, in the same order"""
    data = [
        {
            "name": "Bodega Central Quito",
            "code": "BOD-UIO",
            "address": "Av. 10 de Agosto N37-45",
            "city": "Quito",
            "country": "Ecuador",
            "is_default": True,
            "manager": "Carlos Mendoza",
            "phone": "02-2567890",
            "email": "bodega.uio@faclab.ec",
        },
        {
            "name": "Bodega Guayaquil",
            "code": "BOD-GYE",
            "address": "Km 6.5 Vía Daule",
            "city": "Guayaquil",
            "country": "Ecuador",
            "is_default": False,
            "manager": "Ana Rodríguez",
            "phone": "04-2345678",
            "email": "bodega.gye@faclab.ec",
        },
        {
            "name": "Bodega Cuenca",
            "code": "BOD-CUE",
            "address": "Av. de las Américas 3-42",
            "city": "Cuenca",
            "country": "Ecuador",
            "is_default": False,
            "manager": "Luis Palacios",
            "phone": "07-2834567",
            "email": "bodega.cue@faclab.ec",
        },
    ]
    models = [
        WarehouseModel(branch_id=branch.id, **d)
        for branch, d in zip(branches, data, strict=True)
    ]
    session.add_all(models)
    session.flush()
    return models


def seed_terminals(
    session: Session,
    branches: list[BranchModel],
    warehouses: list[WarehouseModel],
    locations: list[LocationModel],
) -> list[PosTerminalModel]:
    """A terminal per branch that sells from its warehouse's main storage (A1)"""
    points = {
        point.branch_id: point
        for point in session.query(EmissionPointModel).filter(
            EmissionPointModel.branch_id.in_([b.id for b in branches])
        )
    }
    models = []
    for branch, warehouse in zip(branches, warehouses, strict=True):
        prefix = warehouse.code.split("-")[1]
        storage = next(loc for loc in locations if loc.code == f"{prefix}-A1")
        models.append(
            PosTerminalModel(
                branch_id=branch.id,
                emission_point_id=points[branch.id].id,
                default_location_id=storage.id,
                code="CAJA-01",
                name=f"Caja 1 {prefix}",
            )
        )
    session.add_all(models)
    session.flush()
    return models


def seed_locations(
    session: Session, warehouses: list[WarehouseModel]
) -> list[LocationModel]:
    location_specs = [
        ("A1", "Almacén Principal", LocationType.STORAGE, 500),
        ("A2", "Almacén Secundario", LocationType.STORAGE, 300),
        ("R1", "Muelle de Recepción", LocationType.RECEIVING, 100),
        ("S1", "Muelle de Despacho", LocationType.SHIPPING, 100),
        ("Q1", "Inspección de Calidad", LocationType.QUALITY, 50),
    ]
    models = []
    for wh in warehouses:
        prefix = wh.code.split("-")[1]
        for code_suffix, name, loc_type, capacity in location_specs:
            loc = LocationModel(
                warehouse_id=wh.id,
                name=f"{name} - {wh.name}",
                code=f"{prefix}-{code_suffix}",
                type=loc_type,
                capacity=capacity,
            )
            models.append(loc)
    session.add_all(models)
    session.flush()
    return models


def seed_products(
    session: Session,
    categories: list[CategoryModel],
    uoms: list[UnitOfMeasureModel],
) -> list[ProductModel]:
    uom_map = {u.symbol: u.id for u in uoms}
    cat_map = {c.name: c.id for c in categories}

    products_data = [
        # Electrónica (uom: und except cable=m)
        ("ELEC-001", "Cable UTP Cat 6", "Electrónica", "m", 0.45, 0.85, 100, 50),
        (
            "ELEC-002",
            "Switch de red 8 puertos",
            "Electrónica",
            "und",
            18.50,
            32.00,
            10,
            5,
        ),
        ("ELEC-003", "Router WiFi dual band", "Electrónica", "und", 35.00, 55.00, 8, 4),
        (
            "ELEC-004",
            "Cámara de seguridad IP",
            "Electrónica",
            "und",
            45.00,
            75.00,
            5,
            3,
        ),
        ("ELEC-005", "Cable HDMI 2m", "Electrónica", "und", 3.50, 7.00, 20, 10),
        # Ferretería
        ("FERR-001", "Taladro percutor 13mm", "Ferretería", "und", 65.00, 95.00, 5, 3),
        (
            "FERR-002",
            "Juego destornilladores x12",
            "Ferretería",
            "und",
            12.00,
            22.00,
            15,
            8,
        ),
        ("FERR-003", "Cemento Holcim 50kg", "Ferretería", "und", 7.80, 9.50, 50, 30),
        (
            "FERR-004",
            "Varilla corrugada 12mm",
            "Ferretería",
            "und",
            8.50,
            12.00,
            40,
            20,
        ),
        (
            "FERR-005",
            "Disco de corte 7 pulgadas",
            "Ferretería",
            "und",
            2.20,
            4.50,
            30,
            15,
        ),
        # Oficina
        ("OFIC-001", "Resma papel A4 75g", "Oficina", "paq", 3.80, 5.50, 50, 25),
        ("OFIC-002", "Tóner HP 85A", "Oficina", "und", 28.00, 45.00, 10, 5),
        ("OFIC-003", "Archivador de cartón", "Oficina", "und", 1.50, 3.00, 40, 20),
        ("OFIC-004", "Grapadora industrial", "Oficina", "und", 8.00, 15.00, 10, 5),
        ("OFIC-005", "Marcadores permanentes x4", "Oficina", "paq", 2.50, 4.80, 25, 12),
        # Limpieza
        (
            "LIMP-001",
            "Desinfectante industrial 5L",
            "Limpieza",
            "gal",
            8.50,
            14.00,
            20,
            10,
        ),
        ("LIMP-002", "Escoba industrial", "Limpieza", "und", 4.00, 7.50, 15, 8),
        ("LIMP-003", "Guantes de caucho (par)", "Limpieza", "par", 1.80, 3.50, 50, 25),
        ("LIMP-004", "Trapeador industrial", "Limpieza", "und", 5.00, 9.00, 15, 8),
        ("LIMP-005", "Jabón líquido galón", "Limpieza", "gal", 6.00, 10.50, 20, 10),
        # Seguridad Industrial
        (
            "SEGU-001",
            "Casco de seguridad",
            "Seguridad Industrial",
            "und",
            8.00,
            15.00,
            20,
            10,
        ),
        (
            "SEGU-002",
            "Botas punta de acero",
            "Seguridad Industrial",
            "par",
            32.00,
            55.00,
            10,
            5,
        ),
        (
            "SEGU-003",
            "Gafas de protección",
            "Seguridad Industrial",
            "und",
            3.50,
            7.00,
            30,
            15,
        ),
        (
            "SEGU-004",
            "Chaleco reflectivo",
            "Seguridad Industrial",
            "und",
            5.00,
            9.50,
            25,
            12,
        ),
        (
            "SEGU-005",
            "Mascarilla N95 caja x20",
            "Seguridad Industrial",
            "caja",
            12.00,
            22.00,
            15,
            8,
        ),
        # Iluminación
        ("ILUM-001", "Foco LED 12W", "Iluminación", "und", 1.80, 3.50, 50, 25),
        ("ILUM-002", "Tubo fluorescente T8", "Iluminación", "und", 3.50, 6.00, 30, 15),
        ("ILUM-003", "Panel LED 60x60", "Iluminación", "und", 18.00, 32.00, 10, 5),
        ("ILUM-004", "Reflector LED 50W", "Iluminación", "und", 15.00, 28.00, 8, 4),
        ("ILUM-005", "Cinta LED 5m RGB", "Iluminación", "rollo", 6.00, 12.00, 15, 8),
        # Plomería
        ("PLOM-001", "Tubo PVC 4 pulgadas 3m", "Plomería", "und", 5.50, 9.00, 20, 10),
        ("PLOM-002", "Codo PVC 4 pulgadas", "Plomería", "und", 0.80, 1.80, 40, 20),
        ("PLOM-003", "Llave de paso 1/2 pulgada", "Plomería", "und", 4.50, 8.50, 15, 8),
        ("PLOM-004", "Teflón rollo", "Plomería", "rollo", 0.50, 1.20, 50, 25),
        ("PLOM-005", "Pegamento PVC 250ml", "Plomería", "und", 3.00, 5.50, 20, 10),
    ]
    models = []
    for sku, name, cat_name, uom_sym, pp, sp, min_s, reorder in products_data:
        p = ProductModel(
            sku=sku,
            name=name,
            category_id=cat_map[cat_name],
            unit_of_measure_id=uom_map[uom_sym],
            purchase_price=Decimal(str(pp)),
            sale_price=Decimal(str(sp)),
            min_stock=min_s,
            reorder_point=reorder,
            is_active=True,
            is_service=False,
        )
        models.append(p)
    session.add_all(models)
    session.flush()
    return models


def seed_customers(session: Session) -> list[CustomerModel]:
    data = [
        {
            "name": "Constructora Andina S.A.",
            "tax_id": "1790016919001",
            "tax_type": 1,
            "email": "ventas@constructoraandina.ec",
            "phone": "02-2567100",
            "address": "Av. República E7-123",
            "city": "Quito",
            "state": "Pichincha",
            "country": "Ecuador",
            "credit_limit": Decimal("10000.00"),
            "payment_terms": 30,
        },
        {
            "name": "Ferretería El Maestro",
            "tax_id": "0992339411001",
            "tax_type": 1,
            "email": "info@elmaestro.ec",
            "phone": "04-2345600",
            "address": "Av. 25 de Julio, Solar 5",
            "city": "Guayaquil",
            "state": "Guayas",
            "country": "Ecuador",
            "credit_limit": Decimal("5000.00"),
            "payment_terms": 15,
        },
        {
            "name": "Municipio de Cuenca",
            "tax_id": "0160000210001",
            "tax_type": 1,
            "email": "compras@cuenca.gob.ec",
            "phone": "07-2845000",
            "address": "Calle Bolívar 7-67",
            "city": "Cuenca",
            "state": "Azuay",
            "country": "Ecuador",
            "credit_limit": Decimal("50000.00"),
            "payment_terms": 60,
        },
        {
            "name": "Hospital Metropolitano",
            "tax_id": "1791714319001",
            "tax_type": 1,
            "email": "adquisiciones@hmetro.ec",
            "phone": "02-3998000",
            "address": "Av. Mariana de Jesús s/n",
            "city": "Quito",
            "state": "Pichincha",
            "country": "Ecuador",
            "credit_limit": Decimal("25000.00"),
            "payment_terms": 45,
        },
        {
            "name": "Importadora del Sur",
            "tax_id": "0190123456001",
            "tax_type": 1,
            "email": "compras@importadorasur.ec",
            "phone": "07-2823456",
            "address": "Av. Remigio Crespo 1-45",
            "city": "Cuenca",
            "state": "Azuay",
            "country": "Ecuador",
            "credit_limit": Decimal("8000.00"),
            "payment_terms": 30,
        },
        {
            "name": "Juan Carlos Pérez Morales",
            "tax_id": "1710034065",
            "tax_type": 2,
            "email": "jcperez@gmail.com",
            "phone": "0991234567",
            "address": "Calle Amazonas N24-15",
            "city": "Quito",
            "state": "Pichincha",
            "country": "Ecuador",
        },
        {
            "name": "María Elena Zambrano",
            "tax_id": "0912345678",
            "tax_type": 2,
            "email": "mezambrano@hotmail.com",
            "phone": "0987654321",
            "address": "Cdla. Kennedy Norte Mz 4",
            "city": "Guayaquil",
            "state": "Guayas",
            "country": "Ecuador",
        },
        {
            "name": "Roberto Espinoza Calle",
            "tax_id": "0102345678",
            "tax_type": 2,
            "email": "respinoza@outlook.com",
            "phone": "0976543210",
            "address": "Gran Colombia 5-67",
            "city": "Cuenca",
            "state": "Azuay",
            "country": "Ecuador",
        },
        {
            "name": "Condominio Torres del Norte",
            "tax_id": "1792012345001",
            "tax_type": 1,
            "email": "admin@torresdelnorte.ec",
            "phone": "02-2890123",
            "address": "Av. De los Shyris N40-12",
            "city": "Quito",
            "state": "Pichincha",
            "country": "Ecuador",
            "credit_limit": Decimal("3000.00"),
            "payment_terms": 15,
        },
        {
            "name": "Taller Mecánico El Rayo",
            "tax_id": "1791234567001",
            "tax_type": 1,
            "email": "contacto@elrayo.ec",
            "phone": "02-2456789",
            "address": "Panamericana Sur Km 12",
            "city": "Quito",
            "state": "Pichincha",
            "country": "Ecuador",
            "credit_limit": Decimal("2000.00"),
            "payment_terms": 15,
        },
    ]
    models = [CustomerModel(**d) for d in data]
    session.add_all(models)
    session.flush()
    return models


def seed_customer_contacts(
    session: Session, customers: list[CustomerModel]
) -> list[CustomerContactModel]:
    contacts_data = [
        (
            0,
            "Ana María López",
            "Gerente de Compras",
            "alopez@constructoraandina.ec",
            "02-2567101",
        ),
        (
            0,
            "Pedro Sánchez",
            "Contador",
            "psanchez@constructoraandina.ec",
            "02-2567102",
        ),
        (1, "Diego Morales", "Administrador", "dmorales@elmaestro.ec", "04-2345601"),
        (
            2,
            "Ing. Patricia Vélez",
            "Directora de Adquisiciones",
            "pvelez@cuenca.gob.ec",
            "07-2845010",
        ),
        (2, "Carlos Ríos", "Asistente de Compras", "crios@cuenca.gob.ec", "07-2845011"),
        (
            3,
            "Dra. Laura Figueroa",
            "Jefa de Logística",
            "lfigueroa@hmetro.ec",
            "02-3998010",
        ),
        (3, "Marcos Salazar", "Bodeguero", "msalazar@hmetro.ec", "02-3998020"),
        (
            4,
            "Gabriela Andrade",
            "Gerente General",
            "gandrade@importadorasur.ec",
            "07-2823457",
        ),
        (
            8,
            "Fernando Ortiz",
            "Administrador",
            "fortiz@torresdelnorte.ec",
            "02-2890124",
        ),
        (9, "Miguel Ángel Rayo", "Propietario", "mrayo@elrayo.ec", "02-2456790"),
    ]
    models = []
    for idx, name, role, email, phone in contacts_data:
        c = CustomerContactModel(
            customer_id=customers[idx].id,
            name=name,
            role=role,
            email=email,
            phone=phone,
        )
        models.append(c)
    session.add_all(models)
    session.flush()
    return models


def seed_suppliers(session: Session) -> list[SupplierModel]:
    data = [
        {
            "name": "Distribuidora Eléctrica Nacional",
            "tax_id": "1790012345001",
            "tax_type": 1,
            "email": "ventas@distelectrica.ec",
            "phone": "02-2567800",
            "address": "Av. Eloy Alfaro N45-23",
            "city": "Quito",
            "country": "Ecuador",
            "payment_terms": 30,
            "lead_time_days": 5,
        },
        {
            "name": "Importadora Ferretera del Pacífico",
            "tax_id": "0990012345001",
            "tax_type": 1,
            "email": "pedidos@ferreterapacifico.ec",
            "phone": "04-2890123",
            "address": "Parque Industrial Pascuales",
            "city": "Guayaquil",
            "country": "Ecuador",
            "payment_terms": 45,
            "lead_time_days": 7,
        },
        {
            "name": "Papelería y Suministros Quito",
            "tax_id": "1791012345001",
            "tax_type": 1,
            "email": "ventas@papeleriasuministros.ec",
            "phone": "02-2234567",
            "address": "Calle Juan León Mera N23-56",
            "city": "Quito",
            "country": "Ecuador",
            "payment_terms": 15,
            "lead_time_days": 3,
        },
        {
            "name": "Productos Químicos del Ecuador",
            "tax_id": "0990123456001",
            "tax_type": 1,
            "email": "ventas@proquimec.ec",
            "phone": "04-2567890",
            "address": "Km 10.5 Vía Daule",
            "city": "Guayaquil",
            "country": "Ecuador",
            "payment_terms": 30,
            "lead_time_days": 5,
        },
        {
            "name": "Equipos de Seguridad PROSEG",
            "tax_id": "1792345678001",
            "tax_type": 1,
            "email": "ventas@proseg.ec",
            "phone": "02-2678901",
            "address": "Av. Galo Plaza Lasso N56-78",
            "city": "Quito",
            "country": "Ecuador",
            "payment_terms": 30,
            "lead_time_days": 10,
        },
        {
            "name": "Materiales de Construcción MegaCon",
            "tax_id": "1790567890001",
            "tax_type": 1,
            "email": "pedidos@megacon.ec",
            "phone": "02-2789012",
            "address": "Panamericana Norte Km 5",
            "city": "Quito",
            "country": "Ecuador",
            "payment_terms": 60,
            "lead_time_days": 3,
        },
    ]
    models = [SupplierModel(**d) for d in data]
    session.add_all(models)
    session.flush()
    return models


def seed_supplier_contacts(
    session: Session, suppliers: list[SupplierModel]
) -> list[SupplierContactModel]:
    contacts_data = [
        (
            0,
            "Ricardo Mora",
            "Ejecutivo de Ventas",
            "rmora@distelectrica.ec",
            "02-2567801",
        ),
        (0, "Sofía Paredes", "Facturación", "sparedes@distelectrica.ec", "02-2567802"),
        (
            1,
            "Jorge Benítez",
            "Gerente Comercial",
            "jbenitez@ferreterapacifico.ec",
            "04-2890124",
        ),
        (
            2,
            "Lucía Herrera",
            "Ventas Corporativas",
            "lherrera@papeleriasuministros.ec",
            "02-2234568",
        ),
        (
            3,
            "Esteban Moreira",
            "Ejecutivo de Cuenta",
            "emoreira@proquimec.ec",
            "04-2567891",
        ),
        (4, "Daniela Guzmán", "Directora Comercial", "dguzman@proseg.ec", "02-2678902"),
        (4, "Andrés Ponce", "Logística", "aponce@proseg.ec", "02-2678903"),
        (5, "Manuel Vásquez", "Ventas Mayoristas", "mvasquez@megacon.ec", "02-2789013"),
    ]
    models = []
    for idx, name, role, email, phone in contacts_data:
        c = SupplierContactModel(
            supplier_id=suppliers[idx].id,
            name=name,
            role=role,
            email=email,
            phone=phone,
        )
        models.append(c)
    session.add_all(models)
    session.flush()
    return models


def seed_supplier_products(
    session: Session,
    suppliers: list[SupplierModel],
    products: list[ProductModel],
) -> list[SupplierProductModel]:
    sku_map = {p.sku: p.id for p in products}
    # supplier[0] = Distribuidora Eléctrica → ELEC products
    # supplier[1] = Importadora Ferretera → FERR products
    # supplier[2] = Papelería y Suministros → OFIC products
    # supplier[3] = Productos Químicos → LIMP products
    # supplier[4] = Equipos PROSEG → SEGU products
    # supplier[5] = MegaCon → FERR + PLOM + ILUM products
    data = [
        (0, "ELEC-001", 0.40, "DE-CAB6", 100, 3, True),
        (0, "ELEC-002", 17.00, "DE-SW8P", 5, 5, True),
        (0, "ELEC-003", 33.00, "DE-RTWF", 3, 5, True),
        (0, "ELEC-004", 42.00, "DE-CMIP", 2, 7, True),
        (0, "ELEC-005", 3.00, "DE-HDMI", 10, 3, True),
        (1, "FERR-001", 60.00, "IF-TAL13", 3, 7, True),
        (1, "FERR-002", 11.00, "IF-DEST12", 10, 5, True),
        (1, "FERR-005", 2.00, "IF-DC7", 20, 5, True),
        (2, "OFIC-001", 3.50, "PS-RESMA", 20, 2, True),
        (2, "OFIC-002", 26.00, "PS-TON85A", 5, 3, True),
        (2, "OFIC-003", 1.20, "PS-ARCH", 30, 2, True),
        (2, "OFIC-004", 7.50, "PS-GRAP", 5, 3, False),
        (2, "OFIC-005", 2.20, "PS-MARC4", 15, 2, True),
        (3, "LIMP-001", 7.50, "PQ-DES5L", 10, 4, True),
        (3, "LIMP-003", 1.50, "PQ-GUAN", 50, 3, True),
        (3, "LIMP-005", 5.50, "PQ-JABON", 10, 4, True),
        (4, "SEGU-001", 7.00, "PR-CASCO", 10, 8, True),
        (4, "SEGU-002", 30.00, "PR-BOTAS", 5, 10, True),
        (4, "SEGU-003", 3.00, "PR-GAFAS", 20, 5, True),
        (4, "SEGU-004", 4.50, "PR-CHALECO", 15, 5, True),
        (4, "SEGU-005", 10.00, "PR-N95", 10, 8, True),
        (5, "FERR-003", 7.20, "MC-CEM50", 100, 2, True),
        (5, "FERR-004", 8.00, "MC-VAR12", 50, 3, True),
        (5, "PLOM-001", 5.00, "MC-PVC4", 20, 3, True),
        (5, "PLOM-002", 0.70, "MC-CODO4", 50, 3, True),
        (5, "ILUM-001", 1.50, "MC-LED12", 50, 3, False),
    ]
    models = []
    for sup_idx, sku, price, sup_sku, min_qty, lead, preferred in data:
        sp = SupplierProductModel(
            supplier_id=suppliers[sup_idx].id,
            product_id=sku_map[sku],
            purchase_price=Decimal(str(price)),
            supplier_sku=sup_sku,
            min_order_quantity=min_qty,
            lead_time_days=lead,
            is_preferred=preferred,
        )
        models.append(sp)
    session.add_all(models)
    session.flush()
    return models


def seed_lots(session: Session, products: list[ProductModel]) -> list[LotModel]:
    sku_map = {p.sku: p.id for p in products}
    data = [
        ("LIMP-001", "LOT-LIMP001-2025A", date(2025, 6, 1), date(2026, 6, 1), 50, 35),
        ("LIMP-001", "LOT-LIMP001-2025B", date(2025, 9, 1), date(2026, 9, 1), 40, 40),
        ("LIMP-005", "LOT-LIMP005-2025A", date(2025, 7, 1), date(2026, 7, 1), 30, 20),
        ("SEGU-005", "LOT-SEGU005-2025A", date(2025, 5, 1), date(2027, 5, 1), 100, 80),
        ("SEGU-005", "LOT-SEGU005-2025B", date(2025, 10, 1), date(2027, 10, 1), 50, 50),
        ("PLOM-005", "LOT-PLOM005-2025A", date(2025, 3, 1), date(2026, 3, 1), 40, 25),
        ("SEGU-003", "LOT-SEGU003-2025A", date(2025, 8, 1), date(2028, 8, 1), 60, 45),
        ("LIMP-003", "LOT-LIMP003-2025A", date(2025, 4, 1), date(2026, 10, 1), 80, 60),
    ]
    models = []
    for sku, lot_num, mfg, exp, init_qty, curr_qty in data:
        lot = LotModel(
            product_id=sku_map[sku],
            lot_number=lot_num,
            manufacture_date=mfg,
            expiration_date=exp,
            initial_quantity=init_qty,
            current_quantity=curr_qty,
        )
        models.append(lot)
    session.add_all(models)
    session.flush()
    return models


def seed_movements_and_stocks(
    session: Session,
    products: list[ProductModel],
    locations: list[LocationModel],
    lots: list[LotModel],
) -> tuple[list[MovementModel], list[StockModel], list[MovementLotItemModel]]:
    # Location references: warehouses have 5 locations each (A1, A2, R1, S1, Q1)
    # Index 0-4: BOD-UIO, 5-9: BOD-GYE, 10-14: BOD-CUE
    uio_a1 = locations[0]  # BOD-UIO main storage
    gye_a1 = locations[5]  # BOD-GYE main storage
    cue_a1 = locations[10]  # BOD-CUE main storage

    sku_map = {p.sku: p for p in products}

    # Stock ledger to track quantities
    ledger: dict[tuple[int, int], int] = {}
    movements = []
    lot_items = []
    now = datetime.now()

    def add_movement(
        product_id,
        quantity,
        mov_type,
        location_id,
        ref_type=None,
        ref_id=None,
        reason=None,
    ):
        m = MovementModel(
            product_id=product_id,
            quantity=quantity,
            type=mov_type,
            location_id=location_id,
            reference_type=ref_type,
            reference_id=ref_id,
            reason=reason,
            date=now,
        )
        movements.append(m)
        key = (product_id, location_id)
        ledger[key] = ledger.get(key, 0) + quantity
        return m

    # Initial stock IN for all products at BOD-UIO-A1
    initial_quantities = {
        "ELEC-001": 200,
        "ELEC-002": 25,
        "ELEC-003": 15,
        "ELEC-004": 12,
        "ELEC-005": 40,
        "FERR-001": 10,
        "FERR-002": 30,
        "FERR-003": 100,
        "FERR-004": 80,
        "FERR-005": 60,
        "OFIC-001": 80,
        "OFIC-002": 20,
        "OFIC-003": 60,
        "OFIC-004": 15,
        "OFIC-005": 40,
        "LIMP-001": 50,
        "LIMP-002": 20,
        "LIMP-003": 80,
        "LIMP-004": 20,
        "LIMP-005": 30,
        "SEGU-001": 40,
        "SEGU-002": 15,
        "SEGU-003": 60,
        "SEGU-004": 35,
        "SEGU-005": 100,
        "ILUM-001": 80,
        "ILUM-002": 50,
        "ILUM-003": 15,
        "ILUM-004": 12,
        "ILUM-005": 25,
        "PLOM-001": 30,
        "PLOM-002": 60,
        "PLOM-003": 20,
        "PLOM-004": 80,
        "PLOM-005": 40,
    }
    for sku, qty in initial_quantities.items():
        p = sku_map[sku]
        add_movement(
            p.id,
            qty,
            MovementType.IN,
            uio_a1.id,
            "initial_stock",
            None,
            "Carga inicial de inventario",
        )

    # Some stock at BOD-GYE
    gye_stock = {
        "FERR-003": 50,
        "FERR-004": 40,
        "FERR-005": 30,
        "LIMP-001": 25,
        "LIMP-002": 10,
        "LIMP-003": 40,
        "PLOM-001": 15,
        "PLOM-002": 30,
    }
    for sku, qty in gye_stock.items():
        p = sku_map[sku]
        add_movement(
            p.id,
            qty,
            MovementType.IN,
            gye_a1.id,
            "initial_stock",
            None,
            "Carga inicial Guayaquil",
        )

    # Some stock at BOD-CUE
    cue_stock = {
        "SEGU-001": 15,
        "SEGU-002": 8,
        "SEGU-003": 20,
        "ILUM-001": 30,
        "ILUM-002": 20,
        "ILUM-003": 8,
    }
    for sku, qty in cue_stock.items():
        p = sku_map[sku]
        add_movement(
            p.id,
            qty,
            MovementType.IN,
            cue_a1.id,
            "initial_stock",
            None,
            "Carga inicial Cuenca",
        )

    # Some OUT movements for sales (will be linked to sales later by reference)
    sale_outs = [
        ("FERR-003", 20, uio_a1.id),
        ("FERR-005", 10, uio_a1.id),
        ("ELEC-002", 3, uio_a1.id),
        ("ELEC-005", 5, uio_a1.id),
        ("SEGU-001", 10, uio_a1.id),
        ("SEGU-003", 15, uio_a1.id),
        ("SEGU-005", 5, uio_a1.id),
        ("OFIC-001", 10, uio_a1.id),
        ("OFIC-002", 2, uio_a1.id),
    ]
    for sku, qty, loc_id in sale_outs:
        p = sku_map[sku]
        add_movement(p.id, -qty, MovementType.OUT, loc_id, "sale", None, "Venta")

    session.add_all(movements)
    session.flush()

    # Link some movements to lots (the initial IN movements for lot-tracked products)
    lot_number_map = {lot.lot_number: lot for lot in lots}
    lot_movement_links = [
        ("LIMP-001", "LOT-LIMP001-2025A", 50),
        ("LIMP-005", "LOT-LIMP005-2025A", 30),
        ("SEGU-005", "LOT-SEGU005-2025A", 100),
        ("LIMP-003", "LOT-LIMP003-2025A", 80),
        ("SEGU-003", "LOT-SEGU003-2025A", 60),
        ("PLOM-005", "LOT-PLOM005-2025A", 40),
    ]
    # Find the corresponding IN movements for these products at UIO
    movement_by_product_loc = {}
    for m in movements:
        if m.type == MovementType.IN and m.location_id == uio_a1.id:
            movement_by_product_loc[m.product_id] = m

    for sku, lot_num, qty in lot_movement_links:
        p = sku_map[sku]
        mov = movement_by_product_loc.get(p.id)
        lot = lot_number_map[lot_num]
        if mov:
            mli = MovementLotItemModel(
                movement_id=mov.id,
                lot_id=lot.id,
                quantity=qty,
            )
            lot_items.append(mli)

    if lot_items:
        session.add_all(lot_items)
        session.flush()

    # Generate stocks from ledger
    stocks = []
    for (product_id, location_id), quantity in ledger.items():
        if quantity != 0:
            s = StockModel(
                product_id=product_id,
                location_id=location_id,
                quantity=quantity,
                reserved_quantity=0,
            )
            stocks.append(s)
    session.add_all(stocks)
    session.flush()

    return movements, stocks, lot_items


def seed_serial_numbers(
    session: Session,
    products: list[ProductModel],
    lots: list[LotModel],
    locations: list[LocationModel],
) -> list[SerialNumberModel]:
    sku_map = {p.sku: p.id for p in products}
    uio_a1_id = locations[0].id

    data = [
        # Cámaras IP: 3 available, 1 sold, 1 reserved
        (sku_map["ELEC-004"], "CAM-IP-2025-001", "available", uio_a1_id),
        (sku_map["ELEC-004"], "CAM-IP-2025-002", "available", uio_a1_id),
        (sku_map["ELEC-004"], "CAM-IP-2025-003", "available", uio_a1_id),
        (sku_map["ELEC-004"], "CAM-IP-2025-004", "sold", uio_a1_id),
        (sku_map["ELEC-004"], "CAM-IP-2025-005", "reserved", uio_a1_id),
        # Routers: 4 available, 1 sold
        (sku_map["ELEC-003"], "RTR-WF-2025-001", "available", uio_a1_id),
        (sku_map["ELEC-003"], "RTR-WF-2025-002", "available", uio_a1_id),
        (sku_map["ELEC-003"], "RTR-WF-2025-003", "available", uio_a1_id),
        (sku_map["ELEC-003"], "RTR-WF-2025-004", "available", uio_a1_id),
        (sku_map["ELEC-003"], "RTR-WF-2025-005", "sold", uio_a1_id),
        # Switches: all available
        (sku_map["ELEC-002"], "SW-8P-2025-001", "available", uio_a1_id),
        (sku_map["ELEC-002"], "SW-8P-2025-002", "available", uio_a1_id),
        (sku_map["ELEC-002"], "SW-8P-2025-003", "available", uio_a1_id),
        (sku_map["ELEC-002"], "SW-8P-2025-004", "available", uio_a1_id),
        (sku_map["ELEC-002"], "SW-8P-2025-005", "available", uio_a1_id),
    ]
    models = []
    for product_id, serial, status, loc_id in data:
        sn = SerialNumberModel(
            product_id=product_id,
            serial_number=serial,
            status=status,
            location_id=loc_id,
        )
        models.append(sn)
    session.add_all(models)
    session.flush()
    return models


def seed_purchase_orders(
    session: Session,
    suppliers: list[SupplierModel],
    products: list[ProductModel],
    locations: list[LocationModel],
) -> tuple[list, list, list, list]:
    sku_map = {p.sku: p for p in products}
    uio_a1_id = locations[0].id
    uio_r1_id = locations[2].id  # Receiving dock

    orders = []
    order_items = []
    receipts = []
    receipt_items = []

    # PO-2025-001: Received (Distribuidora Eléctrica → ELEC products)
    po1 = PurchaseOrderModel(
        supplier_id=suppliers[0].id,
        order_number="PO-2025-001",
        status="received",
        subtotal=Decimal("545.00"),
        tax=Decimal("81.75"),
        total=Decimal("626.75"),
        notes="Pedido mensual de electrónicos",
        expected_date=datetime(2025, 11, 15),
    )
    orders.append(po1)
    session.add(po1)
    session.flush()

    po1_items_data = [
        ("ELEC-002", 10, 10, Decimal("17.00")),
        ("ELEC-003", 5, 5, Decimal("33.00")),
        ("ELEC-005", 20, 20, Decimal("3.00")),
    ]
    for sku, qty_ord, qty_recv, cost in po1_items_data:
        p = sku_map[sku]
        item = PurchaseOrderItemModel(
            purchase_order_id=po1.id,
            product_id=p.id,
            quantity_ordered=qty_ord,
            quantity_received=qty_recv,
            unit_cost=cost,
        )
        order_items.append(item)
    session.add_all(order_items[-3:])
    session.flush()

    rcpt1 = PurchaseReceiptModel(
        purchase_order_id=po1.id,
        notes="Recepción completa",
        received_at=datetime(2025, 11, 14),
    )
    receipts.append(rcpt1)
    session.add(rcpt1)
    session.flush()

    for oi in order_items[-3:]:
        ri = PurchaseReceiptItemModel(
            purchase_receipt_id=rcpt1.id,
            purchase_order_item_id=oi.id,
            product_id=oi.product_id,
            quantity_received=oi.quantity_received,
            location_id=uio_r1_id,
        )
        receipt_items.append(ri)
    session.add_all(receipt_items[-3:])
    session.flush()

    # PO-2025-002: Received (Importadora Ferretera → FERR products)
    po2 = PurchaseOrderModel(
        supplier_id=suppliers[1].id,
        order_number="PO-2025-002",
        status="received",
        subtotal=Decimal("430.00"),
        tax=Decimal("64.50"),
        total=Decimal("494.50"),
        notes="Reposición herramientas",
        expected_date=datetime(2025, 12, 1),
    )
    orders.append(po2)
    session.add(po2)
    session.flush()

    po2_items_data = [
        ("FERR-001", 5, 5, Decimal("60.00")),
        ("FERR-002", 10, 10, Decimal("11.00")),
        ("FERR-005", 20, 20, Decimal("2.00")),
    ]
    for sku, qty_ord, qty_recv, cost in po2_items_data:
        p = sku_map[sku]
        item = PurchaseOrderItemModel(
            purchase_order_id=po2.id,
            product_id=p.id,
            quantity_ordered=qty_ord,
            quantity_received=qty_recv,
            unit_cost=cost,
        )
        order_items.append(item)
    session.add_all(order_items[-3:])
    session.flush()

    rcpt2 = PurchaseReceiptModel(
        purchase_order_id=po2.id,
        notes="Recepción completa",
        received_at=datetime(2025, 12, 1),
    )
    receipts.append(rcpt2)
    session.add(rcpt2)
    session.flush()

    for oi in order_items[-3:]:
        ri = PurchaseReceiptItemModel(
            purchase_receipt_id=rcpt2.id,
            purchase_order_item_id=oi.id,
            product_id=oi.product_id,
            quantity_received=oi.quantity_received,
            location_id=uio_a1_id,
        )
        receipt_items.append(ri)
    session.add_all(receipt_items[-3:])
    session.flush()

    # PO-2025-003: Sent (Papelería → OFIC products)
    po3 = PurchaseOrderModel(
        supplier_id=suppliers[2].id,
        order_number="PO-2025-003",
        status="sent",
        subtotal=Decimal("200.00"),
        tax=Decimal("30.00"),
        total=Decimal("230.00"),
        expected_date=datetime(2026, 3, 15),
    )
    orders.append(po3)
    session.add(po3)
    session.flush()

    po3_items_data = [
        ("OFIC-001", 30, 0, Decimal("3.50")),
        ("OFIC-002", 5, 0, Decimal("26.00")),
    ]
    for sku, qty_ord, qty_recv, cost in po3_items_data:
        p = sku_map[sku]
        item = PurchaseOrderItemModel(
            purchase_order_id=po3.id,
            product_id=p.id,
            quantity_ordered=qty_ord,
            quantity_received=qty_recv,
            unit_cost=cost,
        )
        order_items.append(item)
    session.add_all(order_items[-2:])
    session.flush()

    # PO-2025-004: Draft (Productos Químicos → LIMP products)
    po4 = PurchaseOrderModel(
        supplier_id=suppliers[3].id,
        order_number="PO-2025-004",
        status="draft",
        subtotal=Decimal("225.00"),
        tax=Decimal("33.75"),
        total=Decimal("258.75"),
    )
    orders.append(po4)
    session.add(po4)
    session.flush()

    po4_items_data = [
        ("LIMP-001", 15, 0, Decimal("7.50")),
        ("LIMP-003", 30, 0, Decimal("1.50")),
        ("LIMP-005", 10, 0, Decimal("5.50")),
    ]
    for sku, qty_ord, qty_recv, cost in po4_items_data:
        p = sku_map[sku]
        item = PurchaseOrderItemModel(
            purchase_order_id=po4.id,
            product_id=p.id,
            quantity_ordered=qty_ord,
            quantity_received=qty_recv,
            unit_cost=cost,
        )
        order_items.append(item)
    session.add_all(order_items[-3:])
    session.flush()

    # PO-2025-005: Cancelled (PROSEG → SEGU products)
    po5 = PurchaseOrderModel(
        supplier_id=suppliers[4].id,
        order_number="PO-2025-005",
        status="cancelled",
        subtotal=Decimal("130.00"),
        tax=Decimal("19.50"),
        total=Decimal("149.50"),
        notes="Cancelado por cambio de proveedor",
    )
    orders.append(po5)
    session.add(po5)
    session.flush()

    po5_items_data = [
        ("SEGU-001", 10, 0, Decimal("7.00")),
        ("SEGU-002", 2, 0, Decimal("30.00")),
    ]
    for sku, qty_ord, qty_recv, cost in po5_items_data:
        p = sku_map[sku]
        item = PurchaseOrderItemModel(
            purchase_order_id=po5.id,
            product_id=p.id,
            quantity_ordered=qty_ord,
            quantity_received=qty_recv,
            unit_cost=cost,
        )
        order_items.append(item)
    session.add_all(order_items[-2:])
    session.flush()

    return orders, order_items, receipts, receipt_items


def seed_sales(
    session: Session,
    customers: list[CustomerModel],
    products: list[ProductModel],
) -> tuple[list, list, list]:
    sku_map = {p.sku: p for p in products}
    sales = []
    items = []
    payments = []

    # Sale 1: CONFIRMED, PAID (Constructora Andina)
    s1_items_data = [
        ("FERR-003", 20, Decimal("9.50"), Decimal("0")),
        ("FERR-005", 10, Decimal("4.50"), Decimal("0")),
        ("SEGU-001", 10, Decimal("15.00"), Decimal("5")),
    ]
    s1_subtotal = sum(
        qty * price * (1 - disc / 100) for _, qty, price, disc in s1_items_data
    )
    s1_tax = s1_subtotal * Decimal("0.15")
    s1_total = s1_subtotal + s1_tax

    s1 = SaleModel(
        customer_id=customers[0].id,
        status="CONFIRMED",
        sale_date=datetime(2026, 1, 15),
        subtotal=s1_subtotal,
        tax=s1_tax,
        total=s1_total,
        payment_status="PAID",
        created_by="admin",
    )
    sales.append(s1)
    session.add(s1)
    session.flush()

    for sku, qty, price, disc in s1_items_data:
        p = sku_map[sku]
        si = SaleItemModel(
            sale_id=s1.id,
            product_id=p.id,
            quantity=qty,
            unit_price=price,
            discount=disc,
        )
        items.append(si)
    session.add_all(items[-3:])
    session.flush()

    pay1 = PaymentModel(
        sale_id=s1.id,
        amount=s1_total,
        payment_method="CASH",
        payment_date=datetime(2026, 1, 15),
        reference="REC-001",
    )
    payments.append(pay1)
    session.add(pay1)
    session.flush()

    # Sale 2: CONFIRMED, PAID (Ferretería El Maestro)
    s2_items_data = [
        ("ELEC-002", 3, Decimal("32.00"), Decimal("0")),
        ("ELEC-005", 5, Decimal("7.00"), Decimal("0")),
    ]
    s2_subtotal = sum(
        qty * price * (1 - disc / 100) for _, qty, price, disc in s2_items_data
    )
    s2_tax = s2_subtotal * Decimal("0.15")
    s2_total = s2_subtotal + s2_tax

    s2 = SaleModel(
        customer_id=customers[1].id,
        status="CONFIRMED",
        sale_date=datetime(2026, 2, 1),
        subtotal=s2_subtotal,
        tax=s2_tax,
        total=s2_total,
        payment_status="PAID",
        created_by="admin",
    )
    sales.append(s2)
    session.add(s2)
    session.flush()

    for sku, qty, price, disc in s2_items_data:
        p = sku_map[sku]
        si = SaleItemModel(
            sale_id=s2.id,
            product_id=p.id,
            quantity=qty,
            unit_price=price,
            discount=disc,
        )
        items.append(si)
    session.add_all(items[-2:])
    session.flush()

    pay2 = PaymentModel(
        sale_id=s2.id,
        amount=s2_total,
        payment_method="TRANSFER",
        payment_date=datetime(2026, 2, 2),
        reference="TRF-20260201-001",
    )
    payments.append(pay2)
    session.add(pay2)
    session.flush()

    # Sale 3: CONFIRMED, PARTIAL (Hospital Metropolitano)
    s3_items_data = [
        ("SEGU-003", 15, Decimal("7.00"), Decimal("0")),
        ("SEGU-005", 5, Decimal("22.00"), Decimal("0")),
        ("OFIC-001", 10, Decimal("5.50"), Decimal("0")),
    ]
    s3_subtotal = sum(
        qty * price * (1 - disc / 100) for _, qty, price, disc in s3_items_data
    )
    s3_tax = s3_subtotal * Decimal("0.15")
    s3_total = s3_subtotal + s3_tax

    s3 = SaleModel(
        customer_id=customers[3].id,
        status="CONFIRMED",
        sale_date=datetime(2026, 2, 15),
        subtotal=s3_subtotal,
        tax=s3_tax,
        total=s3_total,
        payment_status="PARTIAL",
        created_by="admin",
    )
    sales.append(s3)
    session.add(s3)
    session.flush()

    for sku, qty, price, disc in s3_items_data:
        p = sku_map[sku]
        si = SaleItemModel(
            sale_id=s3.id,
            product_id=p.id,
            quantity=qty,
            unit_price=price,
            discount=disc,
        )
        items.append(si)
    session.add_all(items[-3:])
    session.flush()

    pay3 = PaymentModel(
        sale_id=s3.id,
        amount=Decimal("150.00"),
        payment_method="CREDIT_CARD",
        payment_date=datetime(2026, 2, 15),
        reference="CARD-20260215-001",
        notes="Pago parcial con tarjeta de crédito",
    )
    payments.append(pay3)
    session.add(pay3)
    session.flush()

    # Sale 4: DRAFT, PENDING (Juan Carlos Pérez)
    s4_items_data = [
        ("OFIC-002", 2, Decimal("45.00"), Decimal("0")),
        ("OFIC-005", 3, Decimal("4.80"), Decimal("0")),
    ]
    s4_subtotal = sum(
        qty * price * (1 - disc / 100) for _, qty, price, disc in s4_items_data
    )
    s4_tax = s4_subtotal * Decimal("0.15")
    s4_total = s4_subtotal + s4_tax

    s4 = SaleModel(
        customer_id=customers[5].id,
        status="DRAFT",
        subtotal=s4_subtotal,
        tax=s4_tax,
        total=s4_total,
        payment_status="PENDING",
        created_by="admin",
    )
    sales.append(s4)
    session.add(s4)
    session.flush()

    for sku, qty, price, disc in s4_items_data:
        p = sku_map[sku]
        si = SaleItemModel(
            sale_id=s4.id,
            product_id=p.id,
            quantity=qty,
            unit_price=price,
            discount=disc,
        )
        items.append(si)
    session.add_all(items[-2:])
    session.flush()

    # Sale 5: DRAFT, PENDING (María Elena Zambrano)
    s5_items_data = [
        ("ILUM-001", 20, Decimal("3.50"), Decimal("10")),
    ]
    s5_subtotal = sum(
        qty * price * (1 - disc / 100) for _, qty, price, disc in s5_items_data
    )
    s5_tax = s5_subtotal * Decimal("0.15")
    s5_total = s5_subtotal + s5_tax

    s5 = SaleModel(
        customer_id=customers[6].id,
        status="DRAFT",
        subtotal=s5_subtotal,
        tax=s5_tax,
        total=s5_total,
        payment_status="PENDING",
        created_by="admin",
    )
    sales.append(s5)
    session.add(s5)
    session.flush()

    for sku, qty, price, disc in s5_items_data:
        p = sku_map[sku]
        si = SaleItemModel(
            sale_id=s5.id,
            product_id=p.id,
            quantity=qty,
            unit_price=price,
            discount=disc,
        )
        items.append(si)
    session.add_all(items[-1:])
    session.flush()

    # Sale 6: CANCELLED (Roberto Espinoza)
    s6_items_data = [
        ("PLOM-001", 5, Decimal("9.00"), Decimal("0")),
        ("PLOM-003", 3, Decimal("8.50"), Decimal("0")),
    ]
    s6_subtotal = sum(
        qty * price * (1 - disc / 100) for _, qty, price, disc in s6_items_data
    )
    s6_tax = s6_subtotal * Decimal("0.15")
    s6_total = s6_subtotal + s6_tax

    s6 = SaleModel(
        customer_id=customers[7].id,
        status="CANCELLED",
        subtotal=s6_subtotal,
        tax=s6_tax,
        total=s6_total,
        payment_status="PENDING",
        created_by="admin",
    )
    sales.append(s6)
    session.add(s6)
    session.flush()

    for sku, qty, price, disc in s6_items_data:
        p = sku_map[sku]
        si = SaleItemModel(
            sale_id=s6.id,
            product_id=p.id,
            quantity=qty,
            unit_price=price,
            discount=disc,
        )
        items.append(si)
    session.add_all(items[-2:])
    session.flush()

    return sales, items, payments


def seed_adjustments(
    session: Session,
    warehouses: list[WarehouseModel],
    products: list[ProductModel],
    locations: list[LocationModel],
) -> tuple[list, list]:
    sku_map = {p.sku: p.id for p in products}
    uio_a1_id = locations[0].id
    gye_a1_id = locations[5].id

    adjustments = []
    adj_items = []

    # Adjustment 1: CONFIRMED (physical count at BOD-UIO)
    adj1 = InventoryAdjustmentModel(
        warehouse_id=warehouses[0].id,
        reason="physical_count",
        status="confirmed",
        adjustment_date=datetime(2026, 1, 31),
        notes="Conteo físico mensual enero 2026",
        adjusted_by="Carlos Mendoza",
    )
    adjustments.append(adj1)
    session.add(adj1)
    session.flush()

    adj1_items_data = [
        ("FERR-003", uio_a1_id, 100, 98),
        ("OFIC-003", uio_a1_id, 60, 58),
    ]
    for sku, loc_id, expected, actual in adj1_items_data:
        ai = AdjustmentItemModel(
            adjustment_id=adj1.id,
            product_id=sku_map[sku],
            location_id=loc_id,
            expected_quantity=expected,
            actual_quantity=actual,
        )
        adj_items.append(ai)
    session.add_all(adj_items[-2:])
    session.flush()

    # Adjustment 2: DRAFT (damaged at BOD-GYE)
    adj2 = InventoryAdjustmentModel(
        warehouse_id=warehouses[1].id,
        reason="damaged",
        status="draft",
        notes="Productos dañados por humedad",
        adjusted_by="Ana Rodríguez",
    )
    adjustments.append(adj2)
    session.add(adj2)
    session.flush()

    ai2 = AdjustmentItemModel(
        adjustment_id=adj2.id,
        product_id=sku_map["LIMP-001"],
        location_id=gye_a1_id,
        expected_quantity=25,
        actual_quantity=22,
        notes="3 galones con envase roto",
    )
    adj_items.append(ai2)
    session.add(ai2)
    session.flush()

    # Adjustment 3: CANCELLED (correction at BOD-UIO)
    adj3 = InventoryAdjustmentModel(
        warehouse_id=warehouses[0].id,
        reason="correction",
        status="cancelled",
        notes="Ajuste cancelado - error de digitación",
        adjusted_by="Carlos Mendoza",
    )
    adjustments.append(adj3)
    session.add(adj3)
    session.flush()

    ai3 = AdjustmentItemModel(
        adjustment_id=adj3.id,
        product_id=sku_map["ELEC-001"],
        location_id=uio_a1_id,
        expected_quantity=200,
        actual_quantity=195,
    )
    adj_items.append(ai3)
    session.add(ai3)
    session.flush()

    return adjustments, adj_items


def seed_transfers(
    session: Session,
    locations: list[LocationModel],
    products: list[ProductModel],
) -> tuple[list, list]:
    sku_map = {p.sku: p.id for p in products}
    uio_a1 = locations[0]
    uio_a2 = locations[1]
    gye_a1 = locations[5]
    cue_a1 = locations[10]

    transfers = []
    transfer_items = []

    # Transfer 1: RECEIVED (UIO-A1 → GYE-A1)
    t1 = StockTransferModel(
        source_location_id=uio_a1.id,
        destination_location_id=gye_a1.id,
        status="received",
        transfer_date=datetime(2026, 1, 20),
        requested_by="Ana Rodríguez",
        notes="Reposición de stock Guayaquil",
    )
    transfers.append(t1)
    session.add(t1)
    session.flush()

    t1_items = [
        ("ILUM-001", 15),
        ("ILUM-002", 10),
    ]
    for sku, qty in t1_items:
        ti = StockTransferItemModel(
            transfer_id=t1.id,
            product_id=sku_map[sku],
            quantity=qty,
        )
        transfer_items.append(ti)
    session.add_all(transfer_items[-2:])
    session.flush()

    # Transfer 2: CONFIRMED (UIO-A1 → CUE-A1)
    t2 = StockTransferModel(
        source_location_id=uio_a1.id,
        destination_location_id=cue_a1.id,
        status="confirmed",
        transfer_date=datetime(2026, 2, 25),
        requested_by="Luis Palacios",
        notes="Envío de cascos a Cuenca",
    )
    transfers.append(t2)
    session.add(t2)
    session.flush()

    ti2 = StockTransferItemModel(
        transfer_id=t2.id,
        product_id=sku_map["SEGU-001"],
        quantity=5,
    )
    transfer_items.append(ti2)
    session.add(ti2)
    session.flush()

    # Transfer 3: DRAFT (GYE-A1 → UIO-A2)
    t3 = StockTransferModel(
        source_location_id=gye_a1.id,
        destination_location_id=uio_a2.id,
        status="draft",
        requested_by="Carlos Mendoza",
        notes="Devolución de excedente",
    )
    transfers.append(t3)
    session.add(t3)
    session.flush()

    ti3 = StockTransferItemModel(
        transfer_id=t3.id,
        product_id=sku_map["FERR-003"],
        quantity=10,
    )
    transfer_items.append(ti3)
    session.add(ti3)
    session.flush()

    return transfers, transfer_items


def seed_tenant(session: Session) -> None:
    """The whole catalog and its history in the context's tenant"""
    print("Sembrando categorías...")
    categories = seed_categories(session)

    print("Sembrando unidades de medida...")
    uoms = seed_uoms(session)

    print("Sembrando sucursales y puntos de emisión...")
    branches = seed_branches(session)

    print("Sembrando bodegas...")
    warehouses = seed_warehouses(session, branches)

    print("Sembrando ubicaciones...")
    locations = seed_locations(session, warehouses)

    print("Sembrando terminales...")
    terminals = seed_terminals(session, branches, warehouses, locations)

    print("Sembrando productos...")
    products = seed_products(session, categories, uoms)

    print("Sembrando clientes...")
    customers = seed_customers(session)

    print("Sembrando contactos de clientes...")
    seed_customer_contacts(session, customers)

    print("Sembrando proveedores...")
    suppliers = seed_suppliers(session)

    print("Sembrando contactos de proveedores...")
    seed_supplier_contacts(session, suppliers)

    print("Sembrando productos de proveedores...")
    seed_supplier_products(session, suppliers, products)

    print("Sembrando órdenes de compra...")
    seed_purchase_orders(session, suppliers, products, locations)

    print("Sembrando lotes...")
    lots = seed_lots(session, products)

    print("Sembrando movimientos y stock...")
    seed_movements_and_stocks(session, products, locations, lots)

    print("Sembrando números de serie...")
    seed_serial_numbers(session, products, lots, locations)

    print("Sembrando ventas...")
    seed_sales(session, customers, products)

    print("Sembrando ajustes de inventario...")
    seed_adjustments(session, warehouses, products, locations)

    print("Sembrando transferencias...")
    seed_transfers(session, locations, products)

    print(f"  - {len(categories)} categorías")
    print(f"  - {len(uoms)} unidades de medida")
    print(f"  - {len(branches)} sucursales")
    print(f"  - {len(terminals)} terminales")
    print(f"  - {len(warehouses)} bodegas")
    print(f"  - {len(locations)} ubicaciones")
    print(f"  - {len(products)} productos")
    print(f"  - {len(customers)} clientes")
    print(f"  - {len(suppliers)} proveedores")
    print(f"  - {len(lots)} lotes")


def main():
    ensure_local_environment()
    tenant_ids = provision_tenants()
    factory = get_session_maker()

    # One transaction per tenant, each in its own context: its data is replaced
    for tenant_id in tenant_ids:
        print(f"\nEmpresa {tenant_id}")
        with (
            tenant_scope(TenantContext(tenant_id, TenantSource.TASK)),
            factory() as session,
        ):
            print("Borrando sus datos existentes...")
            truncate_tenant(session, tenant_id)
            seed_tenant(session)
            session.commit()

    print("\nSeed completado exitosamente!")


if __name__ == "__main__":
    main()
