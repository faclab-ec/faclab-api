from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from src.catalog.product.infra.models import CategoryModel, ProductModel
from src.catalog.uom.infra.models import UnitOfMeasureModel
from src.inventory.location.infra.models import LocationModel
from src.inventory.movement.domain.constants import MovementType
from src.inventory.movement.infra.models import MovementModel
from src.inventory.stock.infra.models import StockModel
from src.inventory.warehouse.infra.models import WarehouseModel
from src.shared.infra.database import Base

_TABLES = [
    Base.metadata.tables[model.__tablename__]
    for model in (
        CategoryModel,
        UnitOfMeasureModel,
        ProductModel,
        WarehouseModel,
        LocationModel,
        MovementModel,
        StockModel,
    )
]


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _enable_fks(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine, tables=_TABLES)
    db = sessionmaker(bind=engine)()
    db.add(ProductModel(id=1, name="Product A", sku="SKU-A"))
    db.commit()
    yield db
    db.close()


def test_deleting_product_with_movements_is_rejected(session):
    session.add(MovementModel(product_id=1, quantity=10, type=MovementType.IN))
    session.add(StockModel(product_id=1, quantity=10))
    session.commit()

    session.delete(session.get(ProductModel, 1))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    assert session.query(MovementModel).count() == 1
    assert session.query(StockModel).count() == 1


def test_deleting_product_without_history_succeeds(session):
    session.delete(session.get(ProductModel, 1))
    session.commit()

    assert session.get(ProductModel, 1) is None
