"""Las lecturas de la importación (S5.8), con pocas consultas por lote: cada
lista de claves va en bloques de `IN`, siempre dentro de la empresa"""

from collections import defaultdict
from collections.abc import Iterable, Iterator
from decimal import Decimal
from itertools import islice
from typing import Any, TypeVar

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session
from wireup import injectable

from src.catalog.product.domain.entities import Product
from src.catalog.product.infra.mappers import ProductMapper
from src.catalog.product.infra.models import (
    CategoryModel,
    ProductModel,
    ProductPresentationModel,
)
from src.catalog.uom.infra.models import UnitOfMeasureModel
from src.customers.domain.entities import Customer
from src.customers.infra.mappers import CustomerMapper
from src.customers.infra.models import CustomerModel
from src.imports.app.lookups import (
    ImportLookups,
    LocationRef,
    PresentationRef,
    PriceItemRef,
    PriceListRef,
    UnitRef,
    WarehouseRef,
    key,
)
from src.inventory.location.infra.models import LocationModel
from src.inventory.stock.infra.models import StockModel
from src.inventory.warehouse.infra.models import WarehouseModel
from src.pricing.infra.models import PriceListItemModel, PriceListModel
from src.shared.infra.tenant import tenant_criteria
from src.suppliers.domain.entities import Supplier
from src.suppliers.infra.mappers import SupplierMapper
from src.suppliers.infra.models import SupplierModel

# Keys per IN: well under PostgreSQL's limit of bound parameters
CHUNK = 1000

T = TypeVar("T")


def _chunks(values: Iterable[T]) -> Iterator[list[T]]:
    iterator = iter(dict.fromkeys(values))
    while chunk := list(islice(iterator, CHUNK)):
        yield chunk


def _presentation(model: ProductPresentationModel) -> PresentationRef:
    return PresentationRef(
        id=model.id,
        product_id=model.product_id,
        name=model.name,
        factor=model.factor,
        barcode=model.barcode,
        sale_price=model.sale_price,
        purchase_price=model.purchase_price,
        is_base=model.is_base,
        is_active=model.is_active,
    )


@injectable(lifetime="scoped", as_type=ImportLookups)
class SqlAlchemyImportLookups(ImportLookups):
    def __init__(
        self,
        session: Session,
        products: ProductMapper,
        customers: CustomerMapper,
        suppliers: SupplierMapper,
    ):
        self.session = session
        self.product_mapper = products
        self.customer_mapper = customers
        self.supplier_mapper = suppliers

    def _all(self, model: Any, *criteria: Any) -> list[Any]:
        return list(
            self.session.scalars(
                select(model).where(*tenant_criteria(model), *criteria)
            ).all()
        )

    def _in(self, model: Any, column: Any, values: Iterable[Any]) -> list[Any]:
        found: list[Any] = []
        for chunk in _chunks(values):
            found.extend(self._all(model, column.in_(chunk)))
        return found

    def units(self) -> dict[str, UnitRef]:
        return {
            key(model.symbol): UnitRef(
                model.id, model.symbol, model.name, model.decimals
            )
            for model in self._all(UnitOfMeasureModel)
        }

    def categories(self) -> dict[str, int]:
        found: dict[str, int] = {}
        for model in sorted(self._all(CategoryModel), key=lambda m: m.id):
            found.setdefault(key(model.name), model.id)
        return found

    def products(self, skus: Iterable[str]) -> dict[str, Product]:
        return {
            model.sku: self.product_mapper.to_entity(model)
            for model in self._in(ProductModel, ProductModel.sku, skus)
        }

    def presentations(
        self, product_ids: Iterable[int]
    ) -> dict[int, list[PresentationRef]]:
        found: dict[int, list[PresentationRef]] = defaultdict(list)
        models = self._in(
            ProductPresentationModel, ProductPresentationModel.product_id, product_ids
        )
        for model in sorted(models, key=lambda m: m.id):
            found[model.product_id].append(_presentation(model))
        return dict(found)

    def barcodes(self, barcodes: Iterable[str]) -> dict[str, PresentationRef]:
        return {
            model.barcode: _presentation(model)
            for model in self._in(
                ProductPresentationModel, ProductPresentationModel.barcode, barcodes
            )
        }

    def price_lists(self) -> dict[str, PriceListRef]:
        return {
            key(model.name): PriceListRef(model.id, model.name, model.is_default)
            for model in self._all(PriceListModel)
        }

    def price_items(
        self, price_list_ids: Iterable[int], product_ids: Iterable[int]
    ) -> dict[tuple[int, int, Decimal], PriceItemRef]:
        lists = list(dict.fromkeys(price_list_ids))
        if not lists:
            return {}
        found: dict[tuple[int, int, Decimal], PriceItemRef] = {}
        for chunk in _chunks(product_ids):
            for model in self._all(
                PriceListItemModel,
                PriceListItemModel.price_list_id.in_(lists),
                PriceListItemModel.product_id.in_(chunk),
            ):
                found[
                    (model.price_list_id, model.presentation_id, model.min_quantity)
                ] = PriceItemRef(
                    model.id,
                    model.price_list_id,
                    model.presentation_id,
                    model.min_quantity,
                    model.price,
                )
        return found

    def customers(self, tax_ids: Iterable[str]) -> dict[str, Customer]:
        return {
            model.tax_id: self.customer_mapper.to_entity(model)
            for model in self._in(CustomerModel, CustomerModel.tax_id, tax_ids)
        }

    def suppliers(self, tax_ids: Iterable[str]) -> dict[str, Supplier]:
        return {
            model.tax_id: self.supplier_mapper.to_entity(model)
            for model in self._in(SupplierModel, SupplierModel.tax_id, tax_ids)
        }

    def warehouses(self) -> dict[str, WarehouseRef]:
        found: dict[str, WarehouseRef] = {}
        for model in sorted(self._all(WarehouseModel), key=lambda m: m.id):
            found.setdefault(key(model.code), WarehouseRef(model.id, model.code))
        return found

    def locations(
        self, warehouse_ids: Iterable[int]
    ) -> dict[tuple[int, str], LocationRef]:
        found: dict[tuple[int, str], LocationRef] = {}
        models = self._in(LocationModel, LocationModel.warehouse_id, warehouse_ids)
        for model in sorted(models, key=lambda m: m.id):
            found.setdefault(
                (model.warehouse_id, key(model.code)),
                LocationRef(model.id, model.warehouse_id, model.code),
            )
        return found

    def stock(self, pairs: Iterable[tuple[int, int]]) -> dict[tuple[int, int], Decimal]:
        found: dict[tuple[int, int], Decimal] = {}
        for chunk in _chunks(pairs):
            rows = self.session.execute(
                select(
                    StockModel.product_id,
                    StockModel.location_id,
                    func.sum(StockModel.quantity),
                )
                .where(
                    *tenant_criteria(StockModel),
                    tuple_(StockModel.product_id, StockModel.location_id).in_(chunk),
                )
                .group_by(StockModel.product_id, StockModel.location_id)
            ).all()
            for product_id, location_id, quantity in rows:
                found[(product_id, location_id)] = Decimal(quantity)
        return found
