from collections.abc import Iterator

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.catalog.product.infra.models import CategoryModel, ProductModel
from src.catalog.uom.infra.models import UnitOfMeasureModel
from src.inventory.location.infra.models import LocationModel
from src.inventory.movement.domain.constants import MovementType
from src.inventory.movement.infra.models import MovementModel
from src.inventory.stock.infra.models import StockModel
from src.inventory.warehouse.infra.models import WarehouseModel
from tests.conftest import TEST_TENANT_ID
from tests.sqlite import sqlite_session

_MODELS = (
    CategoryModel,
    UnitOfMeasureModel,
    ProductModel,
    WarehouseModel,
    LocationModel,
    MovementModel,
    StockModel,
)


@pytest.fixture
def session(in_tenant) -> Iterator[Session]:
    db = sqlite_session(_MODELS, foreign_keys=True)
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


def test_deleting_category_keeps_its_products_in_the_tenant(session):
    category = CategoryModel(id=1, name="Herramientas")
    session.add(category)
    session.flush()
    product = session.get(ProductModel, 1)
    product.category = category
    session.commit()

    session.delete(category)
    session.commit()

    product = session.get(ProductModel, 1)
    assert product.category_id is None
    assert product.tenant_id == TEST_TENANT_ID
